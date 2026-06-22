from polybot.model.kalshi_buckets import parse_kalshi_strike

def test_inclusive_range():
    assert parse_kalshi_strike("75-76°") == (75.0, 76.0, "F")

def test_open_ended_below():
    assert parse_kalshi_strike("74° or below") == (None, 74.0, "F")

def test_open_ended_above():
    assert parse_kalshi_strike("83° or above") == (83.0, None, "F")

def test_unparseable_returns_none():
    assert parse_kalshi_strike("mostly cloudy") is None
