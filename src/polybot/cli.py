"""CLI entry points."""

import typer
from rich import print as rprint
from rich.table import Table

from polybot.config import load_settings

app = typer.Typer(no_args_is_help=True, help="Mercury — weather forecast vs. prediction-market verification pipeline")


@app.command()
def discover():
    """List active daily-high temperature markets for configured cities."""
    settings = load_settings()
    from polybot.clients.gamma import find_weather_markets

    rows = find_weather_markets(settings.forecast.cities)
    table = Table(title=f"{len(rows)} bucket markets")
    for col in ("city", "target_date", "question", "yes price"):
        table.add_column(col)
    for r in rows:
        px = r["outcome_prices"][0] if r["outcome_prices"] else "?"
        table.add_row(r["city"], r["target_date"], r["question"][:60], str(px))
    rprint(table)


@app.command(name="log-books")
def log_books(cycles: int = typer.Option(None, help="Stop after N cycles (default: run forever)")):
    """Snapshot order books on a loop (no trading)."""
    from polybot.ingest.orderbook_logger import run_logger

    run_logger(load_settings(), cycles=cycles)


@app.command()
def forecast(city: str = typer.Option(None, help="Limit to one city")):
    """Pull forecasts + observations and print bucket distributions vs market."""
    settings = load_settings()
    from polybot.clients.gamma import find_weather_markets
    from polybot.forecast import ensemble, obs
    from polybot.model import buckets as bm

    cities = {c.name: c for c in settings.forecast.cities}
    rows = find_weather_markets(settings.forecast.cities)
    by_event: dict = {}
    for r in rows:
        if city and city.lower() not in r["city"].lower():
            continue
        by_event.setdefault((r["city"], r["target_date"]), []).append(r)

    for (city_name, date), markets in sorted(by_event.items()):
        c = cities[city_name]
        members = ensemble.get_ensemble_members(c.lat, c.lon, c.tz, date, c.unit)
        running = obs.get_running_max(c.station, c.tz, date, c.unit)
        locked = obs.is_day_locked(c.tz, date, settings.forecast.lock_hour_local)
        parsed = [(m, bm.parse_bucket(m["question"])) for m in markets]
        parsed = [(m, p) for m, p in parsed if p]
        ladder = [(p[0], p[1]) for _, p in parsed]
        obs_eff = None
        if running is not None:
            obs_eff = (
                running + settings.forecast.locked_bias_f
                if locked
                else running - settings.forecast.obs_buffer_f
            )
        probs = bm.ladder_probabilities(
            members, ladder, settings.forecast.kernel_sigma_f, obs_eff, locked,
            settings.forecast.locked_sigma_f,
        )
        table = Table(
            title=f"{city_name} {date} — {len(members)} members, "
            f"obs_max={running}, locked={locked}"
        )
        for col in ("bucket", "model", "market", "diff"):
            table.add_column(col)
        for (m, _), prob in zip(parsed, probs):
            mkt = float(m["outcome_prices"][0]) if m["outcome_prices"] else None
            diff = f"{prob - mkt:+.3f}" if mkt is not None else "?"
            style = "bold green" if mkt is not None and prob - mkt > 0.03 else ""
            table.add_row(m["question"][:55], f"{prob:.3f}", f"{mkt}", diff, style=style)
        rprint(table)


@app.command()
def dashboard(
    port: int = typer.Option(8787, help="Port for the local dashboard"),
    db: str = typer.Option(None, help="DB path to view (default: taker DB; pass data/maker.sqlite3 for the maker run)"),
):
    """Serve the live paper-book dashboard at http://127.0.0.1:PORT."""
    from polybot.dashboard import run_dashboard

    run_dashboard(load_settings(), port=port, db_path=db)


@app.command()
def report():
    """Model calibration and edge report."""
    settings = load_settings()
    from polybot.analysis.edge import calibration_report, pnl_report, spread_report
    from polybot.storage import db

    conn = db.connect(settings.db_path)
    pnl = pnl_report(conn)
    rprint(f"[bold]Realized PnL:[/bold] ${pnl['realized_pnl']:+.2f}   "
           f"[bold]Unrealized:[/bold] ${pnl['unrealized_pnl']:+.2f}")
    rprint(f"Settlements: {pnl['settlements']}")
    if pnl["fills_by_kind"]:
        t = Table(title="Fills")
        for col in ("kind", "n", "contracts", "fees"):
            t.add_column(col)
        for f in pnl["fills_by_kind"]:
            t.add_row(f["kind"], str(f["n"]), f"{f['contracts']:.0f}", f"${f['fees']:+.3f}")
        rprint(t)
    if pnl["open_positions"]:
        t = Table(title="Open positions")
        for col in ("question", "qty", "avg_cost", "mark"):
            t.add_column(col)
        for p in pnl["open_positions"]:
            t.add_row(str(p["question"])[:55], f"{p['qty']:.0f}", f"{p['avg_cost']:.3f}", str(p["mark"]))
        rprint(t)
    spreads = spread_report(conn)
    if spreads:
        t = Table(title="Measured spreads by price band")
        for col in ("band", "n", "avg_spread", "avg_rel_spread"):
            t.add_column(col)
        for s in spreads:
            t.add_row(s["band"], str(s["n"]), f"{s['avg_spread']:.4f}", f"{s['avg_rel_spread']:.1%}")
        rprint(t)
    cal = calibration_report(conn)
    if cal:
        t = Table(title="Calibration (model probs vs outcomes)")
        for col in ("bin", "n", "avg_prob", "win_rate", "brier"):
            t.add_column(col)
        for c in cal:
            t.add_row(c["bin"], str(c["n"]), str(c["avg_prob"]), str(c["win_rate"]), str(c["brier"]))
        rprint(t)
    else:
        rprint("[dim]Calibration: no settled fills yet.[/dim]")


@app.command(name="ingest-once")
def ingest_once():
    """Run one read-only ingestion cycle (Kalshi + Polymarket). No trading."""
    import logging
    logging.basicConfig(level=logging.INFO)
    from polybot.pipeline.ingest import run_once
    rprint(run_once(load_settings()))

@app.command(name="backfill-kalshi")
def backfill_kalshi():
    """Backfill settled Kalshi temperature markets for immediate outcome coverage."""
    import logging
    logging.basicConfig(level=logging.INFO)
    from polybot.pipeline.backfill import run_backfill
    rprint(f"backfilled {run_backfill(load_settings())} markets")

@app.command(name="verify-report")
def verify_report():
    """Model vs. market Brier/log-loss by lead time."""
    from polybot.analysis.verification import score_by_lead_time
    from polybot.pipeline.ingest import _abs
    from polybot.storage import verify_db
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
    from polybot.pipeline.export import export_evaluation, export_json
    from polybot.pipeline.ingest import _abs
    from polybot.storage import verify_db
    s = load_settings()
    conn = verify_db.connect(_abs(s.verify.db_path))
    n = export_evaluation(conn, _abs(out), s.verify.lead_buckets)
    export_json(conn, _abs(out.replace(".parquet", ".json")), s.verify.lead_buckets)
    rprint(f"wrote {n} rows -> {out} (+ .json)")


if __name__ == "__main__":
    app()
