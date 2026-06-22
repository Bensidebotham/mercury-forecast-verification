from polybot.config import QuotingConfig
from polybot.strategy.market_maker import (
    estimate_reward,
    fair_value,
    maker_quotes,
    proximity_score,
)

CFG = QuotingConfig()
BOOK = {"best_bid": 0.48, "best_ask": 0.52, "bid_depth": 100, "ask_depth": 100}


def test_fair_value_blends_mid_and_model():
    # mid=0.50, model=0.40, blend=0.3 -> 0.47
    assert abs(fair_value(0.40, BOOK, 0.3) - 0.47) < 1e-9


def test_fair_value_pure_mid_without_model():
    assert abs(fair_value(None, BOOK, 0.3) - 0.50) < 1e-9


def test_maker_quotes_two_sided_and_inside_band():
    q = maker_quotes("t", 0.50, BOOK, CFG)
    sides = {x.side for x in q}
    assert sides == {"BUY", "SELL"}
    buy = next(x for x in q if x.side == "BUY")
    sell = next(x for x in q if x.side == "SELL")
    assert buy.price < BOOK["best_ask"]   # never crosses
    assert sell.price > BOOK["best_bid"]


def test_maker_pulls_quotes_when_locked():
    assert maker_quotes("t", 0.50, BOOK, CFG, locked=True) == []


def test_maker_skips_outside_reward_band():
    deep_tail = {"best_bid": 0.01, "best_ask": 0.03}
    assert maker_quotes("t", 0.02, deep_tail, CFG) == []  # below 0.10 band


def test_inventory_skew_pushes_quotes_down_when_long():
    flat = maker_quotes("t", 0.50, BOOK, CFG, inventory_qty=0)
    # 20 contracts @ 0.50 = $10 inventory, under the $15 cap so both sides quote
    long = maker_quotes("t", 0.50, BOOK, CFG, inventory_qty=20)
    fb = next(x for x in flat if x.side == "BUY").price
    lb = next(x for x in long if x.side == "BUY").price
    assert lb <= fb  # long inventory -> lower bid (discourage buying more)


def test_inventory_cap_suppresses_buy_side_when_maxed_long():
    q = maker_quotes("t", 0.50, BOOK, CFG, inventory_qty=1000)  # way over cap
    assert all(x.side != "BUY" for x in q)  # no more buying when capped long


def test_proximity_score_max_at_touch():
    assert proximity_score(0.48, 0.48, "BUY", 0.10) == 1.0
    assert proximity_score(0.38, 0.48, "BUY", 0.10) < 1e-6  # one discount away ~0
    assert 0 < proximity_score(0.45, 0.48, "BUY", 0.10) < 1


def test_estimate_reward_needs_two_sides():
    one_sided = [type("Q", (), {"side": "BUY", "price": 0.48, "size": 50})()]
    assert estimate_reward(one_sided, BOOK, 1000, 0.10, 100, 86400) == 0.0


def test_estimate_reward_scales_with_share_and_time():
    q = maker_quotes("t", 0.50, BOOK, CFG)
    full_day = estimate_reward(q, BOOK, 1000, 0.10, competitor_depth=0, seconds=86400)
    half_day = estimate_reward(q, BOOK, 1000, 0.10, competitor_depth=0, seconds=43200)
    assert full_day > 0
    assert abs(half_day - full_day / 2) < 1e-6
    # with competitors, our share (and reward) drops
    contested = estimate_reward(q, BOOK, 1000, 0.10, competitor_depth=1000, seconds=86400)
    assert contested < full_day
