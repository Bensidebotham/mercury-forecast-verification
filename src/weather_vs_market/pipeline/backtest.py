"""Retroactive backtest: rebuild what the market and the model said at each lead point.

collect_*   settled ladders, their results, and the market price at each lead
            point from hourly price history (Kalshi candles, Polymarket CLOB).
forecast    det_gauss_v1 probabilities from Open-Meteo Previous Runs, using
            only the lead offset that docs/PROTOCOL.md allows at each point.
score       the protocol's scores over a date window, written to results/.

Every step is resumable: markets already holding a backtest quote are skipped,
and inserts are idempotent.
"""
import json
import logging
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from sqlalchemy import Engine

from weather_vs_market.analysis import verification as V
from weather_vs_market.clients import kalshi
from weather_vs_market.clients import kalshi_history as kh
from weather_vs_market.clients import polymarket_history as ph
from weather_vs_market.config import ROOT, Settings
from weather_vs_market.forecast import iem, previous_runs
from weather_vs_market.model import buckets as bm
from weather_vs_market.model import det_gauss as D
from weather_vs_market.pipeline.fit import TRAIN, VENUE_TRUTH, load_params
from weather_vs_market.pipeline.ingest import target_date_from_ticker, validate_unified
from weather_vs_market.pipeline.publish import lead_points
from weather_vs_market.pipeline.settle import outcome_from_result
from weather_vs_market.storage import store

log = logging.getLogger("wvm.backtest")

TEST = ("2025-07-01", "2026-09-30")
SOURCES = {"kalshi": "kalshi_candles", "polymarket": "polymarket_history"}
MAX_SPREAD = 0.25
# Kalshi emits a candle only for hours with activity; the book persists between
# them, so a standing quote can be hours old and still be the lead-time price.
TOLERANCE_S = 12 * 3600
RESULTS_DIR = ROOT / "results"


def kalshi_price(candle: dict) -> float | None:
    """Mid of a two-sided candle close; None if a side is missing or the spread is wide."""
    bid, ask = candle.get("yes_bid"), candle.get("yes_ask")
    if bid is None or ask is None or ask - bid > MAX_SPREAD:
        return None
    return round((bid + ask) / 2, 4)


def as_of(points: list[tuple[float, float]], point_ts: float,
          tolerance_s: float) -> tuple[float, float] | None:
    """The latest (ts, value) at or before point_ts and within tolerance."""
    best = None
    for ts, v in points:
        if ts <= point_ts and (best is None or ts > best[0]):
            best = (ts, v)
    if best is None or point_ts - best[0] > tolerance_s:
        return None
    return best


def _in(d: str | None, start: str, end: str) -> bool:
    return d is not None and start <= d <= end


def _quoted_uids(engine: Engine, source: str, n_points: int) -> set[str]:
    """Markets that already have a backtest quote for every lead point."""
    counts: dict[str, int] = {}
    for q in store.read_quotes(engine, store.vquote.c.source == source):
        counts[q["market_uid"]] = counts.get(q["market_uid"], 0) + 1
    return {uid for uid, n in counts.items() if n >= n_points}


def kalshi_lead_quote(uid: str, candles: list[dict], point_ts: float, tolerance_s: float,
                      source: str) -> dict | None:
    """The as-of candle's price. If that latest book is one-sided or too wide there is
    no price; an older, tighter candle is never substituted."""
    hit = as_of([(c["ts"], c) for c in candles], point_ts, tolerance_s)
    if hit is None or (price := kalshi_price(hit[1])) is None:
        return None
    c = hit[1]
    return {"ts": c["ts"], "market_uid": uid, "market_prob": price, "best_bid": c["yes_bid"],
            "best_ask": c["yes_ask"], "source": source}


# A CLOB history point may summarize the hour after its timestamp, so it only counts
# as known from the end of that hour. Conservative by up to an hour; never early.
POLYMARKET_LAG_S = 3600


def polymarket_lead_quote(uid: str, history: list[tuple[float, float]], point_ts: float,
                          tolerance_s: float, source: str) -> dict | None:
    hit = as_of([(t + POLYMARKET_LAG_S, p) for t, p in history], point_ts, tolerance_s)
    if hit is None:
        return None
    return {"ts": hit[0], "market_uid": uid, "market_prob": hit[1], "best_bid": None,
            "best_ask": None, "source": source}


FLUSH_EVERY = 200   # markets; keeps a long collection resumable mid-series


def _flush(engine: Engine, markets: list[dict], outcomes: list, quotes: list[dict]) -> None:
    store.upsert_markets(engine, markets)
    store.settle_markets(engine, outcomes)
    store.insert_quotes(engine, quotes)
    markets.clear()
    outcomes.clear()
    quotes.clear()


def collect_kalshi(settings: Settings, engine: Engine, start: str, end: str,
                   only: str | None = None, workers: int = 8, refresh: bool = False) -> dict:
    """`refresh` drops this window's existing quotes first, so a rule change is applied everywhere."""
    lps, tol = lead_points(settings), TOLERANCE_S
    source = SOURCES["kalshi"]
    done = set() if refresh else _quoted_uids(engine, source, len(lps))
    cutoff = kh.fetch_cutoff()
    counts = {"markets": 0, "quotes": 0}
    for vc in settings.venues.kalshi:
        if only and vc.series != only:
            continue
        tz = settings.station(vc.station).tz
        todo = []
        for raw in kh.fetch_settled_markets(vc.series):
            d = target_date_from_ticker(raw["ticker"])
            if not _in(d, start, end):
                continue
            u = kalshi.market_to_unified(raw, vc.city, d)
            outcome = outcome_from_result(raw.get("result"))
            if u is None or not validate_unified(u) or outcome is None:
                continue
            u["station"] = vc.station
            todo.append((raw, u, outcome, [lp.timestamp(d, tz) for lp in lps]))
        if refresh:
            store.delete_quotes(engine, source, [t[1]["market_uid"] for t in todo])

        def lead_quotes(item, series: str = vc.series) -> list[dict]:
            raw, u, _, point_ts = item
            if u["market_uid"] in done:
                return []
            candles = kh.fetch_hourly_quotes(series, raw["ticker"], int(min(point_ts) - tol - 3600),
                                             int(max(point_ts) + 3600), kh.is_historical(raw, cutoff))
            quotes = [kalshi_lead_quote(u["market_uid"], candles, pts, tol, source) for pts in point_ts]
            return [q for q in quotes if q]

        n_quotes = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i in range(0, len(todo), FLUSH_EVERY):
                batch = todo[i:i + FLUSH_EVERY]
                quotes = [q for qs in pool.map(lead_quotes, batch) for q in qs]
                _flush(engine, [b[1] for b in batch], [(b[1]["market_uid"], b[2]) for b in batch], quotes)
                n_quotes += len(quotes)
        log.info("kalshi %s: %d markets, %d quotes", vc.series, len(todo), n_quotes)
        counts["markets"] += len(todo)
        counts["quotes"] += n_quotes
    return counts


def _polymarket_bucket(row: dict) -> tuple[float | None, float | None] | None:
    parsed = bm.parse_bucket(row["question"]) or bm.parse_us_bucket(row["bucket"])
    if parsed is None or parsed[2] != "F":
        return None
    return parsed[0], parsed[1]


def collect_polymarket(settings: Settings, engine: Engine, start: str, end: str,
                       only: str | None = None, refresh: bool = False) -> dict:
    lps, tol = lead_points(settings), TOLERANCE_S
    source = SOURCES["polymarket"]
    done = set() if refresh else _quoted_uids(engine, source, len(lps))
    counts = {"markets": 0, "quotes": 0, "station_mismatch_events": 0}
    for vc in settings.venues.polymarket:
        if only and vc.slug != only:
            continue
        tz = settings.station(vc.station).tz
        events = ph.dedupe_by_date(ph.fetch_series_events(ph.CITY_SERIES[vc.slug]))
        markets, outcomes, quotes = [], [], []
        for d, ev in sorted(events.items()):
            if not _in(d.isoformat(), start, end):
                continue
            rows = ph.parse_event(ev)
            station = rows[0]["station"] if rows else None
            if station is not None and station != vc.station:
                counts["station_mismatch_events"] += 1
                continue
            point_ts = [lp.timestamp(d.isoformat(), tz) for lp in lps]
            for r in rows:
                bucket = _polymarket_bucket(r)
                if bucket is None or r["outcome"] is None:
                    continue
                uid = f"polymarket:{r['token_id']}"
                markets.append({
                    "market_uid": uid, "venue": "polymarket", "external_id": r["token_id"],
                    "event_key": r["event_slug"], "city": vc.city, "station": vc.station,
                    "target_date": d.isoformat(), "bucket_lo": bucket[0], "bucket_hi": bucket[1],
                    "unit": "F", "question": r["question"], "close_ts": r["end_ts"],
                })
                outcomes.append((uid, r["outcome"]))
                if uid in done:
                    continue
                history = ph.fetch_price_history(r["token_id"], int(min(point_ts) - tol - 3600),
                                                 int(max(point_ts) + 3600))
                hits = [polymarket_lead_quote(uid, [(float(t), p) for t, p in history], pts, tol, source)
                        for pts in point_ts]
                quotes += [q for q in hits if q]
        if refresh:
            store.delete_quotes(engine, source, [m["market_uid"] for m in markets])
        store.upsert_markets(engine, markets)
        store.settle_markets(engine, outcomes)
        store.insert_quotes(engine, quotes)
        log.info("polymarket %s: %d markets, %d quotes", vc.slug, len(markets), len(quotes))
        counts["markets"] += len(markets)
        counts["quotes"] += len(quotes)
    return counts


def forecast(settings: Settings, engine: Engine, start: str, end: str) -> dict:
    """det_gauss_v1 predictions at each lead point for every stored ladder in the window.

    Each venue uses parameters fit against its own settlement truth. Existing
    det_gauss_v1 predictions for these markets are replaced, so a re-run never
    leaves stale probabilities behind.
    """
    lps = settings.evaluation.lead_points
    leads = tuple(sorted({lp.previous_run_days for lp in lps}))
    v = store.vmarket
    groups: dict[tuple[str, str], list[dict]] = {}
    for m in store.read_markets(engine, v.c.target_date >= start, v.c.target_date <= end):
        if m["station"] and m["venue"] in VENUE_TRUTH:
            groups.setdefault((m["venue"], m["station"]), []).append(m)
    counts = {"preds": 0, "skipped_no_forecast": 0, "skipped_no_params": 0}
    maxima_cache: dict[str, dict] = {}
    first = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
    for (venue, station_id), markets in sorted(groups.items()):
        params = load_params(VENUE_TRUTH[venue])
        st = settings.station(station_id)
        if station_id not in maxima_cache:
            maxima_cache[station_id] = previous_runs.fetch_daily_max_by_lead(
                st.lat, st.lon, st.tz, first, end, leads=leads, models=D.MODELS)
        maxima = maxima_cache[station_id]
        ladders: dict[str, list[dict]] = {}
        for m in markets:
            ladders.setdefault(m["event_key"], []).append(m)
        preds = []
        for ladder in ladders.values():
            d = ladder[0]["target_date"]
            for lp in lps:
                p = params.get((station_id, lp.previous_run_days))
                if p is None:
                    counts["skipped_no_params"] += 1
                    continue
                fc = D.mean_forecast({mod: maxima[(d, mod, lp.previous_run_days)]
                                      for mod in D.MODELS if (d, mod, lp.previous_run_days) in maxima})
                if fc is None:
                    counts["skipped_no_forecast"] += 1
                    continue
                # Stamped one second before the lead point: the as-of join may use it there.
                ts = V.LeadPoint(lp.name, lp.day_offset, lp.hour).timestamp(d, st.tz) - 1
                probs = D.ladder_probs(fc, p, [(m["bucket_lo"], m["bucket_hi"]) for m in ladder])
                for m, prob in zip(ladder, probs, strict=True):
                    preds.append({"ts": ts, "market_uid": m["market_uid"], "model": D.MODEL,
                                  "model_prob": prob,
                                  "lead_hours": ((m["close_ts"] or ts) - ts) / 3600})
        store.delete_preds(engine, D.MODEL, [m["market_uid"] for m in markets])
        store.insert_preds(engine, preds)
        counts["preds"] += len(preds)
        log.info("%s %s: %d predictions", venue, station_id, len(preds))
    return counts


def cli_agreement(settings: Settings, engine: Engine, start: str, end: str) -> dict:
    """How often the NWS CLI high lands in Kalshi's winning bucket (data-quality check)."""
    v = store.vmarket
    winners = [m for m in store.read_markets(engine, v.c.venue == "kalshi", v.c.outcome == 1,
                                              v.c.target_date >= start, v.c.target_date <= end)]
    highs: dict[tuple[str, str], int] = {}
    for station_id in sorted({m["station"] for m in winners}):
        tz = settings.station(station_id).tz
        for year in range(int(start[:4]), int(end[:4]) + 1):
            for d, h in iem.fetch_cli_highs(station_id, year, tz=tz).items():
                highs[(station_id, d)] = h
    n = agree = 0
    for m in winners:
        h = highs.get((m["station"], m["target_date"]))
        if h is None:
            continue
        n += 1
        lo, hi = m["bucket_lo"], m["bucket_hi"]
        agree += (lo is None or h >= lo) and (hi is None or h <= hi)
    return {"n": n, "agree": agree, "rate": round(agree / n, 4) if n else None}


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def score(settings: Settings, engine: Engine, window: tuple[str, str], name: str) -> dict:
    lps = lead_points(settings)
    doc = {"protocol": "v1", "model": D.MODEL, "window_name": name, "window": list(window),
           "train_window": list(TRAIN), "generated_ts": time.time(), "git_sha": _git_sha(),
           "params": json.loads((ROOT / "config" / "det_gauss_v1.params.json").read_text())["params"],
           "truth_by_venue": VENUE_TRUTH,
           "venues": {}}
    for venue, source in SOURCES.items():
        stats: dict = {}
        events = V.event_frame(engine, venue=venue, model=D.MODEL, lead_points=lps,
                               tz_for_city=settings.city_timezones(venue), quote_sources=(source,),
                               tolerance_s=TOLERANCE_S, date_range=window, stats=stats)
        calibration, by_city = {}, []
        for lp in lps:
            rows = [e for e in events if e["lead"] == lp.name]
            model_pairs, market_pairs = V.calibration_pairs(rows)
            calibration[lp.name] = {"model": V.calibration_curve(model_pairs),
                                    "market": V.calibration_curve(market_pairs)}
            for city in sorted({e["city"] for e in rows}):
                c = [e for e in rows if e["city"] == city]
                by_city.append({"lead": lp.name, "city": city, "n_events": len(c),
                                "model_brier": V.mean([e["model_brier"] for e in c]),
                                "market_brier": V.mean([e["market_brier"] for e in c])})
        doc["venues"][venue] = {
            "summary": V.summarize(events, order=[lp.name for lp in lps]),
            "calibration": calibration, "by_city": by_city,
            "stats": stats,
            "date_span": [min(e["target_date"] for e in events),
                          max(e["target_date"] for e in events)] if events else None,
        }
    doc["data_quality"] = {"kalshi_cli_agreement": cli_agreement(settings, engine, *window)}
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"backtest_{name}.json").write_text(json.dumps(doc, indent=1) + "\n")
    return doc
