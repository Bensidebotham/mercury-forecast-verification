"""Load settings.yaml + .env into typed config objects."""

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
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


class IngestConfig(BaseModel):
    snapshot_interval_seconds: int = 60
    market_filter: dict = {}


class ForecastConfig(BaseModel):
    cities: list[City] = []
    sources: list[str] = ["nws"]
    refresh_interval_minutes: int = 30
    kernel_sigma_f: float = 1.5
    lock_hour_local: int = 18
    earliest_lock_hour: int = 14
    plateau_hours: float = 2.0
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


class QuotingConfig(BaseModel):
    margin: float = 0.02
    max_position_usd: float = 10
    max_event_usd: float = 25
    max_total_usd: float = 80
    max_open_orders_per_market: int = 2
    min_edge_to_quote: float = 0.03
    maker_fill_haircut: float = 0.5
    taker_theta: float = 0.05
    maker_theta: float = -0.0125
    use_calibration: bool = True   # route model probs through learned win-rate curve
    lock_in_only: bool = False     # only trade when the day's high is physically locked in
    paper: bool = True
    # --- market-making params (strategy/market_maker.py) ---
    mm_half_spread: float = 0.02
    mm_size: float = 20            # contracts per side
    mm_max_inventory_usd: float = 15
    mm_skew: float = 1.0           # inventory skew strength (× half_spread at full cap)
    mm_reward_band: tuple[float, float] = (0.10, 0.90)
    mm_fair_blend: float = 0.3     # weight on model vs book-mid for fair value
    mm_pull_on_lock: bool = True
    mm_daily_pool_usd: float = 1000.0   # per-event Climate reward pool (US docs)
    mm_reward_discount: float = 0.30    # Climate discount factor (US docs)
    mm_target_size: float = 10000       # Climate target size, contracts (US docs)
    mm_competitor_factor: float = 3.0   # inflate book depth as competitor-liquidity proxy


class PaperConfig(BaseModel):
    cycle_seconds: int = 60
    discovery_interval_minutes: int = 30
    starting_bankroll_usd: float = 100.0


class Settings(BaseModel):
    ingest: IngestConfig = IngestConfig()
    forecast: ForecastConfig = ForecastConfig()
    quoting: QuotingConfig = QuotingConfig()
    paper: PaperConfig = PaperConfig()
    storage: dict = {"db_path": "data/polybot.sqlite3"}
    # Market-data venue for paper trading. "us" = Polymarket US (the venue we
    # would trade live, via signed gateway calls); "international" = the public
    # gamma/clob endpoints.
    data_source: Literal["us", "international"] = "us"

    @property
    def db_path(self) -> str:
        path = Path(self.storage.get("db_path", "data/polybot.sqlite3"))
        if not path.is_absolute():
            path = ROOT / path
        return str(path)


def load_settings(path: Path | None = None) -> Settings:
    load_dotenv(ROOT / ".env")
    path = path or ROOT / "config" / "settings.yaml"
    with open(path) as f:
        return Settings.model_validate(yaml.safe_load(f))


class Credentials(BaseModel):
    """Polymarket US API credentials (Ed25519 keypair from the developer portal)."""

    key_id: str
    secret_key: str  # base64-encoded Ed25519 private key


def load_credentials() -> Credentials | None:
    """Load Polymarket US creds from .env, or None if unset.

    Returning None keeps paper mode runnable without credentials.
    """
    load_dotenv(ROOT / ".env")
    key_id = os.getenv("POLYMARKET_KEY_ID")
    secret_key = os.getenv("POLYMARKET_SECRET_KEY")
    if not key_id or not secret_key:
        return None
    return Credentials(key_id=key_id, secret_key=secret_key)
