"""One ingestion cycle: discover markets, snapshot market + model probabilities.

Read-only. No orders are ever placed. Safe to run repeatedly (snapshots are
append-only; markets upsert by uid)."""
import logging
import time

from polybot.clients import gamma, kalshi
from polybot.config import City, Settings
from polybot.forecast import ensemble, obs
from polybot.model import buckets as bm
from polybot.storage import verify_db

log = logging.getLogger("mercury.ingest")


def validate_unified(m: dict) -> bool:
    if m.get("close_ts") is None:
        return False
    return m.get("bucket_lo") is not None or m.get("bucket_hi") is not None


def model_prob_for_market(city: City, target_date: str, bucket: dict, *, sigma: float,
                          obs_buffer: float, locked_bias: float, locked_sigma: float) -> float:
    members = ensemble.get_ensemble_members(city.lat, city.lon, city.tz, target_date, city.unit)
    running = obs.get_running_max(city.station, city.tz, target_date, city.unit)
    locked = obs.is_day_locked(city.tz, target_date, 18)
    obs_max = None
    if running is not None:
        obs_max = running + locked_bias if locked else running - obs_buffer
    # bucket_probability(members, lo, hi, sigma, obs_max, locked, locked_sigma)
    return bm.bucket_probability(
        members, bucket["bucket_lo"], bucket["bucket_hi"], sigma, obs_max, locked, locked_sigma
    )


def _abs(p: str) -> str:
    from pathlib import Path
    from polybot.config import ROOT
    pp = Path(p)
    return str(pp if pp.is_absolute() else ROOT / pp)


def _market_cols(u: dict) -> dict:
    return {k: u[k] for k in ("market_uid", "venue", "external_id", "city", "target_date",
                               "bucket_lo", "bucket_hi", "unit", "question", "close_ts")}


def _target_date_from_ticker(ticker: str) -> str:
    import re
    from datetime import datetime
    m = re.search(r"-(\d{2}[A-Z]{3}\d{2})-", ticker)
    if not m:
        return ""
    return datetime.strptime(m.group(1), "%y%b%d").strftime("%Y-%m-%d")


def run_once(settings: Settings) -> dict:
    conn = verify_db.connect(_abs(settings.verify.db_path))
    cities = {c.name: c for c in settings.forecast.cities}
    fc = settings.forecast
    n_markets = n_quotes = n_preds = 0
    now = time.time()
    for city_name in settings.verify.kalshi_cities:
        series = kalshi.CITY_SERIES.get(city_name)
        city = cities.get(city_name)
        if not series or not city:
            log.warning("skip city without series/config: %s", city_name)
            continue
        try:
            raw_markets = kalshi.fetch_markets(series, status="open")
        except Exception as e:
            log.warning("kalshi fetch failed for %s: %s", city_name, e)
            continue
        # Per-(city, date) cache: avoid refetching ensemble/obs for every bucket of the same day.
        _forecast_cache: dict[str, tuple] = {}  # key: target_date -> (members, running, locked)
        for raw in raw_markets:
            try:
                target_date = _target_date_from_ticker(raw["ticker"])
                u = kalshi.market_to_unified(raw, city_name, target_date)
                if u is None or not validate_unified(u):
                    continue
                verify_db.upsert_market(conn, _market_cols(u))
                n_markets += 1
                mp = kalshi.market_prob_from_quote(u["yes_bid"], u["yes_ask"])
                if mp is not None:
                    verify_db.insert_quote(conn, u["market_uid"], now, mp, u["yes_bid"], u["yes_ask"])
                    n_quotes += 1
                # Fetch forecast inputs once per (city, date) within this cycle.
                if target_date not in _forecast_cache:
                    _forecast_cache[target_date] = (
                        ensemble.get_ensemble_members(city.lat, city.lon, city.tz, target_date, city.unit),
                        obs.get_running_max(city.station, city.tz, target_date, city.unit),
                        obs.is_day_locked(city.tz, target_date, 18),
                    )
                members, running, locked = _forecast_cache[target_date]
                obs_max = None
                if running is not None:
                    obs_max = running + fc.locked_bias_f if locked else running - fc.obs_buffer_f
                model_p = bm.bucket_probability(
                    members, u["bucket_lo"], u["bucket_hi"], fc.kernel_sigma_f,
                    obs_max, locked, fc.locked_sigma_f,
                )
                lead_h = max((u["close_ts"] - now) / 3600.0, 0.0)
                verify_db.insert_pred(conn, u["market_uid"], now, model_p, lead_h)
                n_preds += 1
            except Exception as e:
                log.warning("market %s failed: %s", raw.get("ticker"), e)
                continue
    if settings.verify.include_polymarket:
        try:
            _ingest_polymarket(conn, settings, now)
        except Exception as e:
            log.warning("polymarket ingest failed: %s", e)
    log.info("cycle done: markets=%d quotes=%d preds=%d", n_markets, n_quotes, n_preds)
    return {"markets": n_markets, "quotes": n_quotes, "preds": n_preds}


def _ingest_polymarket(conn, settings: Settings, now: float) -> None:
    rows = gamma.find_weather_markets(settings.forecast.cities)
    cities = {c.name: c for c in settings.forecast.cities}
    fc = settings.forecast
    for r in rows:
        parsed = bm.parse_bucket(r["question"])
        if not parsed:
            continue
        lo, hi, unit = parsed
        # gamma rows carry "token_id" (YES token from clobTokenIds[0])
        token = r.get("token_id")
        if not token:
            continue
        uid = f"polymarket:{token}"
        verify_db.upsert_market(conn, {
            "market_uid": uid, "venue": "polymarket", "external_id": token,
            "city": r["city"], "target_date": r["target_date"], "bucket_lo": lo, "bucket_hi": hi,
            "unit": unit, "question": r["question"], "close_ts": r.get("end_ts") or now,
        })
        if r.get("outcome_prices"):
            mp = float(r["outcome_prices"][0])
            verify_db.insert_quote(conn, uid, now, mp, None, None)
        city = cities.get(r["city"])
        if city:
            model_p = model_prob_for_market(
                city, r["target_date"], {"bucket_lo": lo, "bucket_hi": hi},
                sigma=fc.kernel_sigma_f, obs_buffer=fc.obs_buffer_f,
                locked_bias=fc.locked_bias_f, locked_sigma=fc.locked_sigma_f,
            )
            close_ts = conn.execute(
                "SELECT close_ts FROM vmarket WHERE market_uid=?", (uid,)
            ).fetchone()["close_ts"]
            lead_h = max((close_ts - now) / 3600.0, 0.0)
            verify_db.insert_pred(conn, uid, now, model_p, lead_h)
