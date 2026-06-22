from datetime import datetime, timezone
from polybot.clients.kalshi import market_prob_from_quote, market_to_unified

def test_market_prob_is_mid_in_unit_interval():
    assert market_prob_from_quote(yes_bid=40, yes_ask=44) == 0.42

def test_market_prob_handles_one_sided_book():
    assert market_prob_from_quote(yes_bid=None, yes_ask=44) == 0.44
    assert market_prob_from_quote(yes_bid=40, yes_ask=None) == 0.40

def test_market_prob_none_when_no_book():
    assert market_prob_from_quote(None, None) is None

def test_market_to_unified_maps_fields():
    raw = {
        "ticker": "KXHIGHNY-26JUN22-B75", "title": "Highest temp in NYC",
        "subtitle": "75-76°", "yes_bid": 40, "yes_ask": 44,
        "close_time": "2026-06-23T04:00:00Z", "status": "active",
    }
    u = market_to_unified(raw, city="New York", target_date="2026-06-22")
    assert u["market_uid"] == "kalshi:KXHIGHNY-26JUN22-B75"
    assert u["venue"] == "kalshi"
    assert (u["bucket_lo"], u["bucket_hi"]) == (75.0, 76.0)
    assert u["close_ts"] == datetime(2026, 6, 23, 4, 0, 0, tzinfo=timezone.utc).timestamp()

def test_market_to_unified_none_for_unparseable_subtitle():
    raw = {"ticker": "X", "title": "t", "subtitle": "cloudy", "close_time": "2026-06-23T04:00:00Z"}
    assert market_to_unified(raw, city="NYC", target_date="2026-06-22") is None
