"""Backfill settled Kalshi markets so scoring has a sample without waiting.

Settlement history gives the OUTCOME and bucket, not historical order books — so
backfilled markets contribute outcome/settlement coverage and let us validate the
model against truth. Live model-vs-market lead-time scoring still accrues forward."""
import logging

from polybot.clients import kalshi
from polybot.pipeline.ingest import _abs, _market_cols, _target_date_from_ticker
from polybot.storage import verify_db

log = logging.getLogger("mercury.backfill")

def outcome_from_result(result: str | None) -> int | None:
    if result is None:
        return None
    return 1 if result.lower() == "yes" else 0

def settled_rows_to_unified(raw_rows: list[dict], city: str) -> list[dict]:
    out = []
    for raw in raw_rows:
        u = kalshi.market_to_unified(raw, city, _target_date_from_ticker(raw["ticker"]))
        if u is None:
            continue
        u["outcome"] = outcome_from_result(raw.get("result"))
        if u["outcome"] is None:
            continue
        out.append(u)
    return out

def run_backfill(settings) -> int:
    conn = verify_db.connect(_abs(settings.verify.db_path))
    n = 0
    for city_name in settings.verify.kalshi_cities:
        series = kalshi.CITY_SERIES.get(city_name)
        if not series:
            continue
        try:
            raw = kalshi.fetch_settled(series)
        except Exception as e:
            log.warning("settled fetch failed for %s: %s", city_name, e); continue
        for u in settled_rows_to_unified(raw, city_name):
            verify_db.upsert_market(conn, _market_cols(u))
            verify_db.settle_market(conn, u["market_uid"], u["outcome"]); n += 1
    log.info("backfilled %d settled markets", n)
    return n
