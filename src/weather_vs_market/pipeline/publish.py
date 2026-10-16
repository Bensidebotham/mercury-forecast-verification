"""Build the dashboard document and publish it to the store (and optionally a file).

The dashboard reads the newest published_result row through a read-only role,
so a data refresh never needs a redeploy or a commit.
"""
import json
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import Engine

from weather_vs_market.analysis import live
from weather_vs_market.analysis import verification as V
from weather_vs_market.config import ROOT, Settings
from weather_vs_market.pipeline.ingest import ENSEMBLE_MODEL
from weather_vs_market.storage import store

SCHEMA_VERSION = 2
BACKTEST_RESULTS = ROOT / "results" / "backtest.json"


def lead_points(settings: Settings) -> list[V.LeadPoint]:
    return [V.LeadPoint(lp.name, lp.day_offset, lp.hour) for lp in settings.evaluation.lead_points]


def live_scores(settings: Settings, engine: Engine) -> dict:
    """Forward scores of the live ensemble model against live quotes, per venue."""
    out = {}
    for venue in ("kalshi", "polymarket"):
        events = V.event_frame(engine, venue=venue, model=ENSEMBLE_MODEL,
                               lead_points=lead_points(settings),
                               tz_for_city=settings.city_timezones(venue), quote_sources=("live",),
                               tolerance_s=settings.evaluation.tolerance_hours * 3600)
        out[venue] = {"summary": V.summarize(events) if events else [], "n_events": len(events)}
    return out


def build_doc(settings: Settings, engine: Engine, now: float | None = None) -> dict:
    backtest = json.loads(BACKTEST_RESULTS.read_text()) if BACKTEST_RESULTS.exists() else None
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_ts": now if now is not None else time.time(),
        "backtest": backtest,
        "live": {"model": ENSEMBLE_MODEL, "scores": live_scores(settings, engine)},
        "tracking": live.tracking_summary(engine),
        "live_disagreements": live.current_disagreements(engine, model=ENSEMBLE_MODEL, now=now),
    }


def publish(settings: Settings, engine: Engine, out_file: str | None = None) -> dict:
    doc = build_doc(settings, engine)
    store.publish(engine, doc, generated_ts=doc["generated_ts"])
    if out_file:
        Path(out_file).parent.mkdir(parents=True, exist_ok=True)
        Path(out_file).write_text(json.dumps(doc))
    return doc


def dump_tables(engine: Engine, out_dir: str) -> dict[str, int]:
    """Write every table to Parquet so anyone can rerun the analysis offline."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    counts = {}
    for table in (store.vmarket, store.vquote, store.vpred, store.ingest_run):
        rows = store.read_table(engine, table)
        cols = [c.name for c in table.columns]
        pq.write_table(pa.table({c: [r[c] for r in rows] for c in cols}),
                       str(Path(out_dir) / f"{table.name}.parquet"))
        counts[table.name] = len(rows)
    return counts
