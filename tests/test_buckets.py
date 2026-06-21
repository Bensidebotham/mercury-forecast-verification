import math

from polybot.model.buckets import bucket_probability, ladder_probabilities, parse_bucket


def test_parse_between():
    assert parse_bucket(
        "Will the highest temperature in New York City be between 82-83°F on June 10?"
    ) == (82.0, 83.0, "F")


def test_parse_or_higher():
    assert parse_bucket(
        "Will the highest temperature in New York City be 90°F or higher on June 10?"
    ) == (90.0, None, "F")


def test_parse_or_below():
    assert parse_bucket(
        "Will the highest temperature in New York City be 71°F or below on June 10?"
    ) == (None, 71.0, "F")


def test_parse_exact_celsius():
    assert parse_bucket(
        "Will the highest temperature in Seoul be 25°C on June 11?"
    ) == (25.0, 25.0, "C")


def test_parse_rejects_non_bucket():
    assert parse_bucket("Will it rain in NYC on June 10?") is None


def test_bucket_probability_centered():
    # all members at 82.5 with tight kernel -> 82-83 bucket near 1
    p = bucket_probability([82.5] * 30, 82, 83, sigma=0.3)
    assert p > 0.95


def test_ladder_sums_to_one():
    members = [78.0, 80.5, 81.0, 82.0, 83.5, 85.0]
    ladder = [(None, 79.0), (80.0, 81.0), (82.0, 83.0), (84.0, None)]
    probs = ladder_probabilities(members, ladder, sigma=1.5)
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-9)
    assert all(0 <= p <= 1 for p in probs)


def test_obs_truncation_kills_low_buckets():
    members = [75.0, 76.0, 77.0]
    # station already observed 80 -> "below 79" bucket must be ~0
    p_low = bucket_probability(members, None, 78, sigma=1.0, obs_max=80.0)
    assert p_low < 0.01
    p_high = bucket_probability(members, 80, 81, sigma=1.0, obs_max=80.0)
    assert p_high > 0.5


def test_locked_day_collapses_to_obs():
    members = [70.0, 90.0]  # forecast is irrelevant once locked
    p = bucket_probability(members, 82, 83, sigma=1.5, obs_max=82.4, locked=True)
    assert p > 0.9
    p_wrong = bucket_probability(members, 88, 89, sigma=1.5, obs_max=82.4, locked=True)
    assert p_wrong < 0.01
