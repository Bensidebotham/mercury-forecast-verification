import pytest

from weather_vs_market.config import load_settings
from weather_vs_market.pipeline import fit, ingest


def test_locked_residuals_compare_cli_high_to_hourly_max():
    temps = [("2025-06-01T13:51", 88.0), ("2025-06-01T14:51", 89.1), ("2025-06-02T15:51", 80.0)]
    highs = {"2025-06-01": 90, "2025-06-02": 80, "2025-06-03": 70}
    assert fit.locked_residuals(temps, highs) == pytest.approx([0.9, 0.0])


def test_fit_locked_params_mean_and_floored_sd():
    p = fit.locked_params([1.0, 1.0, 1.0] * 40)
    assert p == {"bias": 1.0, "sigma": fit.MIN_LOCKED_SIGMA, "n": 120}


def test_locked_day_uses_station_specific_bias():
    # Running max 89.0 on a locked day at a station whose CLI high runs +1.1F above
    # hourly METAR: the 90-91 bucket must be favored, not 88-89.
    cfg = load_settings().ensemble
    locked = {"KMIA": {"bias": 1.1, "sigma": 0.6, "n": 500}}
    inputs = ([85.0] * 30, 89.0, True)
    p_90 = ingest.ensemble_prob(inputs, 90.0, 91.0, cfg, station="KMIA", locked_params=locked)
    p_88 = ingest.ensemble_prob(inputs, 88.0, 89.0, cfg, station="KMIA", locked_params=locked)
    assert p_90 > p_88
