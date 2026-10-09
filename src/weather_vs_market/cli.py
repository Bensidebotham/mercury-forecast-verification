"""CLI entry points."""

import typer
from rich import print as rprint
from rich.table import Table

from weather_vs_market.config import load_settings

app = typer.Typer(no_args_is_help=True, help="weather-vs-market: score weather-model probabilities against prediction markets")


@app.command()
def ingest():
    """Run one read-only ingestion cycle (Kalshi + Polymarket). No trading."""
    import logging
    logging.basicConfig(level=logging.INFO)
    from weather_vs_market.pipeline.ingest import run_once
    rprint(run_once(load_settings()))

@app.command()
def backfill():
    """Backfill settled Kalshi temperature markets for immediate outcome coverage."""
    import logging
    logging.basicConfig(level=logging.INFO)
    from weather_vs_market.pipeline.backfill import run_backfill
    rprint(f"backfilled {run_backfill(load_settings())} markets")

@app.command()
def report():
    """Model vs. market Brier/log-loss by lead time."""
    from weather_vs_market.analysis.verification import score_by_lead_time
    from weather_vs_market.pipeline.ingest import _abs
    from weather_vs_market.storage import verify_db
    s = load_settings()
    conn = verify_db.connect(_abs(s.verify.db_path))
    rows = score_by_lead_time(conn, s.verify.lead_buckets)
    if not rows:
        rprint("[dim]No settled markets with paired snapshots yet.[/dim]"); return
    t = Table(title="Model vs. Market (lower Brier = better)")
    for col in ("lead_h", "n", "model_brier", "market_brier", "model_logloss", "market_logloss"):
        t.add_column(col)
    for r in rows:
        win = "bold green" if r["model_brier"] < r["market_brier"] else ""
        t.add_row(str(r["lead_hours"]), str(r["n"]), f"{r['model_brier']:.4f}",
                  f"{r['market_brier']:.4f}", f"{r['model_logloss']:.4f}",
                  f"{r['market_logloss']:.4f}", style=win)
    rprint(t)

@app.command(name="export")
def export_cmd(out: str = typer.Option("data/evaluations.parquet")):
    """Export the evaluation frame to Parquet + JSON."""
    from weather_vs_market.pipeline.export import export_evaluation, export_json
    from weather_vs_market.pipeline.ingest import _abs
    from weather_vs_market.storage import verify_db
    s = load_settings()
    conn = verify_db.connect(_abs(s.verify.db_path))
    n = export_evaluation(conn, _abs(out), s.verify.lead_buckets)
    export_json(conn, _abs(out.replace(".parquet", ".json")), s.verify.lead_buckets)
    rprint(f"wrote {n} rows -> {out} (+ .json)")


if __name__ == "__main__":
    app()
