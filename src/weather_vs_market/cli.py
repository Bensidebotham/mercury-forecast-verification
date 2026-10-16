"""CLI entry points. Everything is read-only against the venues: no trading."""

import logging

import typer
from rich import print as rprint
from rich.table import Table

from weather_vs_market.config import load_settings

app = typer.Typer(no_args_is_help=True,
                  help="weather-vs-market: score weather-model probabilities against prediction markets")


def _engine():
    from weather_vs_market.storage import store
    return store.connect(load_settings().database_url())


@app.callback()
def _setup(verbose: bool = typer.Option(False, "--verbose", "-v")):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


@app.command()
def ingest():
    """Snapshot open markets and live model probabilities. Exits 1 if the cycle failed."""
    from weather_vs_market.pipeline.ingest import run_once
    out = run_once(load_settings(), _engine())
    rprint(out)
    if out["status"] != "ok":
        raise typer.Exit(1)


@app.command()
def settle():
    """Mark stored markets settled from venue results."""
    from weather_vs_market.pipeline.settle import run_settle
    rprint(run_settle(load_settings(), _engine()))


@app.command()
def publish(out: str = typer.Option("", help="Also write the dashboard JSON to this file.")):
    """Build the dashboard document and store it for the dashboard to read."""
    from weather_vs_market.pipeline.publish import publish as do_publish
    doc = do_publish(load_settings(), _engine(), out_file=out or None)
    rprint(f"published {doc['tracking']['n_markets']} markets, "
           f"{len(doc['live_disagreements'])} live disagreements")


@app.command()
def dump(out: str = typer.Option("data/dump", help="Directory for the Parquet files.")):
    """Dump every table to Parquet for offline, credential-free reproduction."""
    from weather_vs_market.pipeline.publish import dump_tables
    rprint(dump_tables(_engine(), out))


@app.command()
def fit():
    """Fit det_gauss_v1 on the training window and freeze it in config/."""
    from weather_vs_market.pipeline.fit import PARAMS_FILE, run_fit
    doc = run_fit(load_settings())
    rprint(f"wrote {len(doc['params'])} (station, lead) fits -> {PARAMS_FILE}")


@app.command(name="fit-locked")
def fit_locked():
    """Fit the CLI-vs-hourly-METAR gap per station (training window) for locked days."""
    from weather_vs_market.pipeline.fit import LOCKED_FILE, run_fit_locked
    doc = run_fit_locked(load_settings())
    rprint(doc["stations"])
    rprint(f"-> {LOCKED_FILE}")


backtest_app = typer.Typer(no_args_is_help=True, help="Retroactive backtest (see docs/PROTOCOL.md).")
app.add_typer(backtest_app, name="backtest")


def _window(name: str) -> tuple[str, str]:
    from weather_vs_market.pipeline.backtest import TEST
    from weather_vs_market.pipeline.fit import TRAIN
    windows = {"train": TRAIN, "test": TEST, "dev": ("2025-04-01", "2025-06-30")}
    return windows[name]


@backtest_app.command("collect")
def backtest_collect(venue: str = typer.Argument(..., help="kalshi | polymarket"),
                     window: str = typer.Option("test", help="train | dev | test"),
                     only: str = typer.Option("", help="One Kalshi series or Polymarket city slug.")):
    """Settled ladders, results and lead-point prices for a window."""
    from weather_vs_market.pipeline import backtest as B
    fn = {"kalshi": B.collect_kalshi, "polymarket": B.collect_polymarket}[venue]
    rprint(fn(load_settings(), _engine(), *_window(window), only=only or None))


@backtest_app.command("forecast")
def backtest_forecast(window: str = typer.Option("test", help="train | dev | test")):
    """det_gauss_v1 probabilities at each lead point for stored ladders."""
    from weather_vs_market.pipeline.backtest import forecast
    rprint(forecast(load_settings(), _engine(), *_window(window)))


@backtest_app.command("score")
def backtest_score(window: str = typer.Option("test", help="dev | test")):
    """Score a window per the protocol and write results/backtest_<window>.json."""
    from weather_vs_market.pipeline.backtest import score
    doc = score(load_settings(), _engine(), _window(window), window)
    for venue, v in doc["venues"].items():
        for r in v["summary"]:
            lo, hi = r["brier_diff_ci"]
            rprint(f"{venue:10} {r['lead']:9} n={r['n_events']:4}  Brier model {r['model_brier']:.4f}"
                   f" market {r['market_brier']:.4f}  diff {r['brier_diff']:+.4f} [{lo:+.4f}, {hi:+.4f}]")


@backtest_app.command("report")
def backtest_report():
    """Regenerate the README results block and docs/RESULTS.md from results/backtest_test.json."""
    from weather_vs_market.config import ROOT
    from weather_vs_market.pipeline.report import write_reports
    write_reports(ROOT / "results" / "backtest_test.json", ROOT / "README.md", ROOT / "docs" / "RESULTS.md")
    rprint("updated README.md and docs/RESULTS.md")


@app.command()
def report():
    """Live ensemble model vs. market, per venue and lead point."""
    from weather_vs_market.pipeline.publish import live_scores
    scores = live_scores(load_settings(), _engine())
    for venue, s in scores.items():
        if not s["summary"]:
            rprint(f"[dim]{venue}: no settled events with complete live snapshots yet[/dim]")
            continue
        t = Table(title=f"{venue}: model vs. market (lower is better; diff < 0 = model better)")
        for col in ("lead", "events", "model Brier", "market Brier", "diff [95% CI]"):
            t.add_column(col)
        for r in s["summary"]:
            lo, hi = r["brier_diff_ci"]
            t.add_row(r["lead"], str(r["n_events"]), f"{r['model_brier']:.4f}",
                      f"{r['market_brier']:.4f}", f"{r['brier_diff']:+.4f} [{lo:+.4f}, {hi:+.4f}]")
        rprint(t)


if __name__ == "__main__":
    app()
