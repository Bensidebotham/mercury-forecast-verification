"""Load config/settings.yaml into typed config objects."""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]


class Station(BaseModel):
    id: str
    lat: float
    lon: float
    tz: str
    name: str = ""


class KalshiCity(BaseModel):
    city: str
    series: str
    station: str


class PolymarketCity(BaseModel):
    city: str
    slug: str          # city part of the event slug, e.g. "nyc"
    station: str


class Venues(BaseModel):
    kalshi: list[KalshiCity] = []
    polymarket: list[PolymarketCity] = []


class EnsembleConfig(BaseModel):
    kernel_sigma_f: float = 1.5
    lock_hour_local: int = 18
    obs_buffer_f: float = 1.0
    locked_bias_f: float = 0.0
    locked_sigma_f: float = 0.75


class LeadPointConfig(BaseModel):
    name: str
    day_offset: int
    hour: int
    previous_run_days: int   # Open-Meteo previous_dayN offset the backtest may use here


class EvaluationConfig(BaseModel):
    lead_points: list[LeadPointConfig] = []
    tolerance_hours: float = 2.0


class StorageConfig(BaseModel):
    url: str = "data/verify.sqlite3"


class Settings(BaseModel):
    stations: dict[str, Station]
    venues: Venues = Venues()
    ensemble: EnsembleConfig = EnsembleConfig()
    evaluation: EvaluationConfig = EvaluationConfig()
    storage: StorageConfig = StorageConfig()

    def station(self, station_id: str) -> Station:
        return self.stations[station_id]

    def city_timezones(self, venue: str) -> dict[str, str]:
        return {v.city: self.station(v.station).tz for v in getattr(self.venues, venue)}

    def database_url(self) -> str:
        """DATABASE_URL wins; otherwise a SQLite path relative to the repo root."""
        if url := os.environ.get("DATABASE_URL"):
            return url
        p = Path(self.storage.url)
        return str(p if p.is_absolute() or "://" in self.storage.url else ROOT / p)


def load_settings(path: Path | None = None) -> Settings:
    path = path or ROOT / "config" / "settings.yaml"
    with open(path) as f:
        raw = yaml.safe_load(f)
    raw["stations"] = {k: {"id": k, **v} for k, v in raw.get("stations", {}).items()}
    return Settings.model_validate(raw)
