"""Load config/settings.yaml into typed config objects."""

from pathlib import Path

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]


class City(BaseModel):
    name: str
    station: str
    lat: float
    lon: float
    tz: str = "America/New_York"
    unit: str = "F"
    aliases: list[str] = []


class ForecastConfig(BaseModel):
    cities: list[City] = []
    kernel_sigma_f: float = 1.5
    lock_hour_local: int = 18
    # Hourly METAR maxima undershoot the official CLI daily max (CLI uses
    # continuous sensor peaks). Buffer keeps truncation honest; bias centers
    # locked-day estimates; locked sigma covers the residual uncertainty.
    obs_buffer_f: float = 1.5
    locked_bias_f: float = 0.75
    locked_sigma_f: float = 1.0
    # Coarse global ensembles (25km grid) run hot at coastal stations
    # (KSFO/KLAX marine layer). Shift members this fraction of the way
    # toward the NWS point forecast (2.5km, forecaster-edited).
    nws_blend: float = 0.7


class VerifyConfig(BaseModel):
    db_path: str = "data/verify.sqlite3"
    lead_buckets: tuple[int, ...] = (72, 48, 24, 6)
    kalshi_cities: list[str] = ["New York", "Los Angeles", "Chicago", "Miami", "Austin"]
    include_polymarket: bool = True


class Settings(BaseModel):
    forecast: ForecastConfig = ForecastConfig()
    verify: VerifyConfig = VerifyConfig()


def load_settings(path: Path | None = None) -> Settings:
    path = path or ROOT / "config" / "settings.yaml"
    with open(path) as f:
        return Settings.model_validate(yaml.safe_load(f))

