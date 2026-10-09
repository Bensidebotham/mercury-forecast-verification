from datetime import datetime, timezone
from weather_vs_market.clients.kalshi import market_prob_from_quote, market_to_unified

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

# Current Kalshi v2 payloads (2026-10): `subtitle` is null, the label lives in
# `yes_sub_title`, and the bucket is given structurally by floor/cap strike.
def _current_raw(**over):
    raw = {
        "ticker": "KXHIGHNY-26OCT10-B72.5", "title": "Will the maximum temperature be 72-73° on Oct 10, 2026?",
        "subtitle": None, "yes_sub_title": "72° to 73°", "close_time": "2026-10-11T05:00:00Z",
        "yes_bid": None, "yes_ask": None, "yes_bid_dollars": "0.0200", "yes_ask_dollars": "0.0300",
        "floor_strike": 72, "cap_strike": 73, "strike_type": "between", "status": "active",
    }
    raw.update(over)
    return raw

def test_between_strike_uses_floor_and_cap():
    u = market_to_unified(_current_raw(), city="New York", target_date="2026-10-10")
    assert (u["bucket_lo"], u["bucket_hi"]) == (72.0, 73.0)

def test_greater_strike_is_strictly_above_floor():
    # ">73°" on an integer-reported high means 74 or above.
    raw = _current_raw(ticker="KXHIGHNY-26OCT10-T73", yes_sub_title="74° or above",
                       floor_strike=73, cap_strike=None, strike_type="greater")
    u = market_to_unified(raw, city="New York", target_date="2026-10-10")
    assert (u["bucket_lo"], u["bucket_hi"]) == (74.0, None)

def test_less_strike_is_strictly_below_cap():
    # "<66°" means 65 or below.
    raw = _current_raw(ticker="KXHIGHNY-26OCT10-T66", yes_sub_title="65° or below",
                       floor_strike=None, cap_strike=66, strike_type="less")
    u = market_to_unified(raw, city="New York", target_date="2026-10-10")
    assert (u["bucket_lo"], u["bucket_hi"]) == (None, 65.0)

def test_label_fallback_reads_yes_sub_title_when_no_strikes():
    raw = _current_raw(floor_strike=None, cap_strike=None, strike_type=None)
    u = market_to_unified(raw, city="New York", target_date="2026-10-10")
    assert (u["bucket_lo"], u["bucket_hi"]) == (72.0, 73.0)

def test_null_cent_prices_fall_back_to_dollar_strings():
    from weather_vs_market.clients.kalshi import _normalize_market
    m = _normalize_market(_current_raw())
    assert (m["yes_bid"], m["yes_ask"]) == (2, 3)
