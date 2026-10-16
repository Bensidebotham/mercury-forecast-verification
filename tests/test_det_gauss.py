import math

import pytest

from weather_vs_market.model import det_gauss as D


def test_fit_estimates_bias_and_spread_per_station_and_lead():
    # forecasts run 2F cold with residuals of +1/+3 -> bias 2, sd 1
    samples = []
    for i in range(40):
        fc = 80.0 + i % 5
        samples.append(D.Sample("KMIA", 1, fc, fc + (1.0 if i % 2 else 3.0)))
    params = D.fit(samples, min_samples=30)
    p = params[("KMIA", 1)]
    assert p.bias == pytest.approx(2.0)
    assert p.sigma == pytest.approx(1.0, rel=0.05)
    assert p.n == 40


def test_fit_skips_groups_with_too_few_samples():
    samples = [D.Sample("KNYC", 2, 70.0, 71.0) for _ in range(5)]
    assert D.fit(samples, min_samples=30) == {}


def test_sigma_has_a_floor():
    samples = [D.Sample("KLAX", 1, 70.0, 71.0) for _ in range(40)]   # zero residual spread
    assert D.fit(samples, min_samples=30)[("KLAX", 1)].sigma == D.MIN_SIGMA


def test_ladder_probabilities_sum_to_one_and_center_on_bias_corrected_mean():
    params = D.Params(bias=2.0, sigma=1.0, n=100)
    ladder = [(None, 79.0), (80.0, 81.0), (82.0, 83.0), (84.0, None)]
    probs = D.ladder_probs(80.5, params, ladder)          # corrected mean 82.5
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-9)
    assert max(range(4), key=probs.__getitem__) == 2


def test_mean_forecast_requires_every_model():
    assert D.mean_forecast({"gfs_seamless": 80.0, "ecmwf_ifs025": 82.0}) == 81.0
    assert D.mean_forecast({"gfs_seamless": 80.0}) is None


def test_params_round_trip_through_json():
    params = {("KMIA", 1): D.Params(2.0, 1.5, 300), ("KNYC", 2): D.Params(-0.5, 2.5, 280)}
    assert D.params_from_json(D.params_to_json(params)) == params
