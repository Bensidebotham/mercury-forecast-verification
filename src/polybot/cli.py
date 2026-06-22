"""CLI entry points."""

import typer
from rich import print as rprint
from rich.table import Table

from polybot.config import load_settings

app = typer.Typer(no_args_is_help=True, help="Polymarket weather paper-trading bot")


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


@app.command(name="paper-run")
def paper_run(cycles: int = typer.Option(None, help="Stop after N cycles (default: run forever)")):
    """Run the paper-trading loop: forecast -> signals -> simulated fills."""
    settings = load_settings()
    if not settings.quoting.paper:
        rprint("[red]quoting.paper is false but live trading is not implemented. Refusing.[/red]")
        raise typer.Exit(1)
    from polybot.engine import PaperEngine

    PaperEngine(settings).run(cycles=cycles)


@app.command(name="maker-run")
def maker_run(cycles: int = typer.Option(None, help="Stop after N cycles (default: forever)")):
    """Run the paper MARKET-MAKING loop: two-sided quotes + estimated rewards."""
    from polybot.maker_engine import MakerEngine

    MakerEngine(load_settings()).run(cycles=cycles)


@app.command(name="maker-report")
def maker_report_cmd():
    """P&L attribution for the maker run: rewards vs spread vs adverse selection."""
    from polybot.config import ROOT
    from polybot.maker_engine import maker_report

    r = maker_report(str(ROOT / "data" / "maker.sqlite3"))
    rprint(f"[bold]Reward income (est):[/bold]      ${r['reward_income']:+.2f}")
    rprint(f"[bold]Spread + rebate P&L:[/bold]      ${r['spread_rebate_pnl']:+.2f}")
    rprint(f"[bold]Adverse selection (settle):[/bold] ${r['adverse_selection_pnl']:+.2f}")
    rprint(f"[bold]Unrealized:[/bold]               ${r['unrealized']:+.2f}")
    rprint(f"[bold cyan]NET:[/bold cyan]                         ${r['net']:+.2f}")
    rprint(f"[dim]fills={r['fills']} rebates_paid=${r['rebates_paid']:.3f} "
           f"open_positions={r['open_positions']}[/dim]")


@app.command(name="rewards-gate")
def rewards_gate():
    """Phase-0 gate: confirm Polymarket US exposes liquidity-reward programs (/v1/incentives)."""
    from polybot.clients.us import PolymarketUS

    settings = load_settings()
    client = PolymarketUS.from_env()
    if client is None:
        rprint("[red]No credentials — set POLYMARKET_KEY_ID / POLYMARKET_SECRET_KEY in .env[/red]")
        raise typer.Exit(1)
    rows = client.find_incentivized_markets(settings.rewards.discovery_limit)
    if not rows:
        rprint("[red]GATE FAILED: no open incentivized markets with reward params (spec §3).[/red]")
        raise typer.Exit(1)
    rprint(f"[bold]{len(rows)}[/bold] open incentivized markets with reward programs")
    t = Table(title="Incentivized markets (sample)")
    for col in ("category", "question", "pool$", "target_size", "period"):
        t.add_column(col)
    for r in rows[:15]:
        rw = r["reward"]
        t.add_row(r["category"], r["question"][:45], f"{rw['pool_usd']:.0f}",
                  f"{rw['target_size']:.0f}", rw["period"])
    rprint(t)
    rprint("[green]GATE PASSED.[/green]")


@app.command(name="rewards-run")
def rewards_run(cycles: int = typer.Option(None, help="Stop after N cycles (default: forever)")):
    """Run the incentive-program rewards-MM paper simulator."""
    from polybot.rewards_engine import RewardsEngine

    RewardsEngine(load_settings()).run(cycles=cycles)


@app.command(name="rewards-report")
def rewards_report_cmd():
    """Net = reward range − adverse selection − fees for the rewards-MM run."""
    from polybot.config import ROOT
    from polybot.rewards_engine import rewards_report
    from polybot.storage import db

    settings = load_settings()
    conn = db.connect(str(ROOT / settings.rewards.db_path))
    r = rewards_report(conn)
    rprint(f"[bold]Reward income (est):[/bold] "
           f"${r['reward_pess']:+.2f} .. ${r['reward_opt']:+.2f}  [dim](pess..opt)[/dim]")
    rprint(f"[bold]Adverse selection (inventory PnL):[/bold] ${r['adverse_selection_pnl']:+.2f}")
    rprint(f"[dim]  of which settlement ${r['settlement_pnl']:+.2f}, "
           f"unrealized ${r['unrealized']:+.2f}, fees ${r['fees_paid']:+.3f}[/dim]")
    rprint(f"[bold cyan]NET:[/bold cyan] ${r['net_pess']:+.2f} .. ${r['net_opt']:+.2f}")
    rprint(f"[dim]fills={r['fills']} open_positions={r['open_positions']}[/dim]")
    if r["net_pess"] > 0:
        rprint("[green]Pessimistic net > 0 — go/no-go gate would pass for this period.[/green]")
    else:
        rprint("[yellow]Pessimistic net <= 0 — gate not met.[/yellow]")
    rprint(f"[dim]NB: reward assumes live-program window = "
           f"{settings.rewards.live_period_seconds:.0f}s (unverified assumption — scales reward "
           f"linearly); reward is credited per resting cycle including fill cycles (upward bias). "
           f"Treat the headline as optimistic until calibrated against a real settled program.[/dim]")


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
    """Paper PnL, fill quality, spread measurement, model calibration."""
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
        t = Table(title="Calibration (traded probs vs outcomes)")
        for col in ("bin", "n", "avg_prob", "win_rate", "brier"):
            t.add_column(col)
        for c in cal:
            t.add_row(c["bin"], str(c["n"]), str(c["avg_prob"]), str(c["win_rate"]), str(c["brier"]))
        rprint(t)
    else:
        rprint("[dim]Calibration: no settled fills yet.[/dim]")


if __name__ == "__main__":
    app()
