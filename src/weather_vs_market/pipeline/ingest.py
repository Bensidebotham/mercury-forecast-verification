"""One live ingestion cycle: discover open markets, snapshot market + model probabilities.

Read-only. No orders are ever placed. Safe to re-run: markets upsert by uid and
snapshots are idempotent on (market, ts, source/model).

Failures are skipped and counted, never stored as data: a missing forecast is
not a P=0.0 prediction, and a one-sided book is not a price. A cycle that finds
no markets at all is recorded as failed so an upstream API change is loud.
"""
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Engine

from weather_vs_market.clients import kalshi
from weather_vs_market.clients import polymarket_history as ph
from weather_vs_market.config import EnsembleConfig, Settings
from weather_vs_market.forecast import ensemble, obs
from weather_vs_market.model import buckets as bm
from weather_vs_market.pipeline.fit import load_locked_params
from weather_vs_market.storage import store

log = logging.getLogger("wvm.ingest")

ENSEMBLE_MODEL = "ens_kernel_v1"


def validate_unified(m: dict) -> bool:
    if m.get("close_ts") is None:
        return False
    return m.get("bucket_lo") is not None or m.get("bucket_hi") is not None


def target_date_from_ticker(ticker: str) -> str:
    m = re.search(r"-(\d{2}[A-Z]{3}\d{2})-", ticker)
    if not m:
        return ""
    return datetime.strptime(m.group(1), "%y%b%d").strftime("%Y-%m-%d")


class Forecasts:
    """Ensemble members and station obs, fetched once per (station, date) per cycle."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: dict[tuple[str, str], tuple] = {}
        self.locked_params = load_locked_params()

    def prob(self, station_id: str, target_date: str, lo: float | None, hi: float | None) -> float | None:
        return ensemble_prob(self.get(station_id, target_date), lo, hi, self.settings.ensemble,
                             station=station_id, locked_params=self.locked_params)

    def get(self, station_id: str, target_date: str) -> tuple:
        key = (station_id, target_date)
        if key not in self._cache:
            st = self.settings.station(station_id)
            self._cache[key] = (
                ensemble.get_ensemble_members(st.lat, st.lon, st.tz, target_date, "F"),
                obs.get_running_max(st.id, st.tz, target_date, "F"),
                obs.is_day_locked(st.tz, target_date, self.settings.ensemble.lock_hour_local),
            )
        return self._cache[key]


def ensemble_prob(inputs: tuple, lo: float | None, hi: float | None, cfg: EnsembleConfig,
                  station: str | None = None, locked_params: dict | None = None) -> float | None:
    """ens_kernel_v1 probability for one bucket, or None if there is no forecast.

    On a locked day the distribution centers on the running max plus the
    station's fitted CLI-vs-METAR bias (config/locked_obs.params.json), falling
    back to the global settings when a station has no fit.
    """
    members, running, locked = inputs
    lp = (locked_params or {}).get(station or "")
    bias = lp["bias"] if lp else cfg.locked_bias_f
    sigma = lp["sigma"] if lp else cfg.locked_sigma_f
    obs_max = None
    if running is not None:
        obs_max = running + bias if locked else running - cfg.obs_buffer_f
    try:
        return bm.bucket_probability(members, lo, hi, cfg.kernel_sigma_f, obs_max, locked, sigma)
    except ValueError:
        return None


class Cycle:
    """Rows and counters accumulated over one cycle, written in batches."""

    def __init__(self, now: float):
        self.now = now
        self.markets: list[dict] = []
        self.quotes: list[dict] = []
        self.preds: list[dict] = []
        self.skipped_preds = 0
        self.errors: list[str] = []

    def add(self, market: dict, bid: float | None, ask: float | None, market_prob: float | None,
            model_prob: float | None) -> None:
        self.markets.append(market)
        uid = market["market_uid"]
        if market_prob is not None:
            self.quotes.append({"ts": self.now, "market_uid": uid, "market_prob": market_prob,
                                "best_bid": bid, "best_ask": ask, "source": "live"})
        if model_prob is None:
            self.skipped_preds += 1
        else:
            self.preds.append({"ts": self.now, "market_uid": uid, "model": ENSEMBLE_MODEL,
                               "model_prob": model_prob,
                               "lead_hours": max((market["close_ts"] - self.now) / 3600.0, 0.0)})


def _ingest_kalshi(settings: Settings, forecasts: Forecasts, cycle: Cycle) -> None:
    for venue_city in settings.venues.kalshi:
        try:
            raw_markets = kalshi.fetch_markets(venue_city.series, status="open")
        except Exception as e:
            cycle.errors.append(f"kalshi {venue_city.series}: {e}")
            continue
        for raw in raw_markets:
            try:
                target_date = target_date_from_ticker(raw["ticker"])
                u = kalshi.market_to_unified(raw, venue_city.city, target_date)
                if u is None or not validate_unified(u):
                    continue
                u["station"] = venue_city.station
                model_p = forecasts.prob(venue_city.station, target_date, u["bucket_lo"], u["bucket_hi"])
                cycle.add(u, u["yes_bid"], u["yes_ask"],
                          kalshi.market_prob_from_quote(u["yes_bid"], u["yes_ask"]), model_p)
            except Exception as e:
                cycle.errors.append(f"kalshi {raw.get('ticker')}: {e}")


def polymarket_markets(ev: dict, city: str, station: str) -> list[tuple[dict, float | None, float | None]]:
    """(unified market, best bid, best ask) for each parseable bucket of a Gamma event."""
    out = []
    target = ph.event_date(ev)
    for mkt in ev.get("markets") or []:
        tokens = json.loads(mkt.get("clobTokenIds") or "[]")
        parsed = bm.parse_bucket(mkt.get("question") or "") or bm.parse_us_bucket(
            mkt.get("groupItemTitle") or "")
        if not tokens or parsed is None or parsed[2] != "F" or target is None:
            continue
        end = mkt.get("endDate") or ev.get("endDate")
        out.append(({
            "market_uid": f"polymarket:{tokens[0]}", "venue": "polymarket", "external_id": tokens[0],
            "event_key": ev.get("slug"), "city": city, "station": station,
            "target_date": target.isoformat(), "bucket_lo": parsed[0], "bucket_hi": parsed[1],
            "unit": "F", "question": mkt.get("question"),
            "close_ts": datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp() if end else None,
        }, mkt.get("bestBid"), mkt.get("bestAsk")))
    return out


def _ingest_polymarket(settings: Settings, forecasts: Forecasts, cycle: Cycle) -> None:
    for venue_city in settings.venues.polymarket:
        today = datetime.fromtimestamp(cycle.now, ZoneInfo(settings.station(venue_city.station).tz)).date()
        for d in (today + timedelta(days=i) for i in range(3)):
            try:
                ev = ph.find_event(venue_city.slug, d)
            except Exception as e:
                cycle.errors.append(f"polymarket {venue_city.slug} {d}: {e}")
                continue
            if ev is None or ev.get("closed"):
                continue
            station = ph.resolution_station(ev)
            if station != venue_city.station:
                cycle.errors.append(f"polymarket {ev.get('slug')}: settles on {station}, "
                                    f"expected {venue_city.station}")
                continue
            for u, bid, ask in polymarket_markets(ev, venue_city.city, station):
                if not validate_unified(u):
                    continue
                model_p = forecasts.prob(station, u["target_date"], u["bucket_lo"], u["bucket_hi"])
                cycle.add(u, bid, ask, kalshi.market_prob_from_quote(bid, ask), model_p)


def run_once(settings: Settings, engine: Engine, now: float | None = None) -> dict:
    started = time.time()
    cycle = Cycle(now if now is not None else started)
    forecasts = Forecasts(settings)
    _ingest_kalshi(settings, forecasts, cycle)
    _ingest_polymarket(settings, forecasts, cycle)

    store.upsert_markets(engine, cycle.markets)
    store.insert_quotes(engine, cycle.quotes)
    store.insert_preds(engine, cycle.preds)

    status = "ok" if cycle.markets else "failed"
    summary = {"status": status, "markets": len(cycle.markets), "quotes": len(cycle.quotes),
               "preds": len(cycle.preds), "skipped_preds": cycle.skipped_preds,
               "errors": len(cycle.errors)}
    store.record_run(engine, {
        "run_id": uuid.uuid4().hex, "started_ts": started, "finished_ts": time.time(),
        "status": status, "n_markets": len(cycle.markets), "n_quotes": len(cycle.quotes),
        "n_preds": len(cycle.preds), "n_skipped": cycle.skipped_preds,
        "detail": json.dumps({"errors": cycle.errors[:50]}),
    })
    for e in cycle.errors[:20]:
        log.warning(e)
    log.info("cycle %s", summary)
    return summary
