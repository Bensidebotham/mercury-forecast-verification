"""Load settings.yaml + .env into typed config objects."""

from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]


class IngestConfig(BaseModel):
    snapshot_interval_seconds: int = 60
    market_filter: dict = {}


class ForecastConfig(BaseModel):
    cities: list[dict] = []
    sources: list[str] = ["nws"]
    refresh_interval_minutes: int = 60


class QuotingConfig(BaseModel):
    margin: float = 0.02
    max_position_usd: float = 25
    max_open_orders_per_market: int = 4
    min_edge_to_quote: float = 0.03
    paper: bool = True


class Settings(BaseModel):
    ingest: IngestConfig = IngestConfig()
    forecast: ForecastConfig = ForecastConfig()
    quoting: QuotingConfig = QuotingConfig()
    storage: dict = {"db_path": "data/polybot.sqlite3"}


def load_settings(path: Path | None = None) -> Settings:
    load_dotenv(ROOT / ".env")
    path = path or ROOT / "config" / "settings.yaml"
    with open(path) as f:
        return Settings.model_validate(yaml.safe_load(f))
