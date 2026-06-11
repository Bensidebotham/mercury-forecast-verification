"""CLI entry points — one command per build phase."""

import typer
from rich import print as rprint

from polybot.config import load_settings

app = typer.Typer(no_args_is_help=True, help="Polymarket weather maker bot")


@app.command()
def discover():
    """Phase 1: list active weather/temperature markets."""
    settings = load_settings()
    from polybot.clients.gamma import find_weather_markets

    markets = find_weather_markets(settings.ingest.market_filter.get("tags", []))
    rprint(markets)


@app.command(name="log-books")
def log_books():
    """Phase 1: snapshot order books on a loop (run for ~1 week)."""
    from polybot.ingest.orderbook_logger import run_logger

    run_logger(load_settings())


@app.command()
def forecast():
    """Phase 2: pull forecasts and print bucket distributions."""
    rprint("[yellow]TODO: phase 2[/yellow]")


@app.command(name="edge-report")
def edge_report():
    """Phase 3: model vs market gap analysis from logged data."""
    rprint("[yellow]TODO: phase 3[/yellow]")


@app.command()
def quote(paper: bool = typer.Option(True, help="Paper mode (live not implemented)")):
    """Phase 4: run the maker quoting loop."""
    if not paper:
        rprint("[red]Live trading is not implemented. Refusing.[/red]")
        raise typer.Exit(1)
    rprint("[yellow]TODO: phase 4[/yellow]")


if __name__ == "__main__":
    app()
