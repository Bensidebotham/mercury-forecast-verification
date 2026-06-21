"""Standalone book logger (phase 1) — same data the paper engine logs,
for running spread/depth measurement without any trading simulation."""

import time

from rich.console import Console

from polybot.clients import clob, gamma
from polybot.config import Settings
from polybot.model import buckets as bucket_model
from polybot.storage import db

console = Console()


def run_logger(settings: Settings, cycles: int | None = None) -> None:
    conn = db.connect(settings.db_path)
    markets = {}
    last_discovery = 0.0
    n = 0
    while cycles is None or n < cycles:
        if time.time() - last_discovery > 1800:
            for r in gamma.find_weather_markets(settings.forecast.cities):
                parsed = bucket_model.parse_bucket(r["question"])
                if not parsed:
                    continue
                lo, hi, unit = parsed
                markets[r["token_id"]] = r
                db.upsert_market(
                    conn,
                    {
                        "token_id": r["token_id"], "event_slug": r["event_slug"],
                        "city": r["city"], "target_date": r["target_date"],
                        "question": r["question"], "bucket_lo": lo, "bucket_hi": hi,
                        "unit": unit, "end_ts": r["end_ts"], "closed": int(r["closed"]),
                    },
                )
            last_discovery = time.time()
            console.log(f"discovery: {len(markets)} markets")
        ok = 0
        for tid in markets:
            book = clob.get_order_book(tid)
            if book:
                db.insert_snapshot(conn, tid, book)
                ok += 1
        console.log(f"cycle {n}: snapshotted {ok}/{len(markets)} books")
        n += 1
        if cycles is None or n < cycles:
            time.sleep(settings.ingest.snapshot_interval_seconds)
