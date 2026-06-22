from polybot.strategy.market_maker import MMQuote, estimate_reward_range, reward_quotes

BOOK = {"best_bid": 0.49, "best_ask": 0.51, "bid_depth": 100, "ask_depth": 100}
PARAMS = {"pool_usd": 2000.0, "discount": 0.3, "target_size": 15000.0,
          "period": "live", "program_id": "p"}
AT_BEST = [MMQuote("t", "BUY", 0.49, 200), MMQuote("t", "SELL", 0.51, 200)]


def test_two_sided_at_best_positive_and_ordered():
    opt, pess = estimate_reward_range(AT_BEST, BOOK, PARAMS, tick_size=0.01,
                                      seconds=86400, opt_factor=0.25, pess_factor=1.0)
    assert opt >= pess >= 0.0
    assert opt > 0.0


def test_single_sided_scores_zero_both_bounds():
    one = [MMQuote("t", "BUY", 0.49, 200)]
    opt, pess = estimate_reward_range(one, BOOK, PARAMS, 0.01, 86400, 0.25, 1.0)
    assert opt == 0.0 and pess == 0.0


def test_distance_from_best_reduces_reward():
    far = [MMQuote("t", "BUY", 0.47, 200), MMQuote("t", "SELL", 0.53, 200)]  # 2 ticks out
    at_opt, _ = estimate_reward_range(AT_BEST, BOOK, PARAMS, 0.01, 86400, 0.25, 1.0)
    far_opt, _ = estimate_reward_range(far, BOOK, PARAMS, 0.01, 86400, 0.25, 1.0)
    assert far_opt < at_opt


def test_scales_with_time():
    full, _ = estimate_reward_range(AT_BEST, BOOK, PARAMS, 0.01, 86400, 0.25, 1.0)
    half, _ = estimate_reward_range(AT_BEST, BOOK, PARAMS, 0.01, 43200, 0.25, 1.0)
    assert abs(half - full / 2) < 1e-9


def test_target_size_floor_caps_share():
    big = {**PARAMS, "target_size": 1_000_000.0}
    _, pess = estimate_reward_range(AT_BEST, BOOK, big, 0.01, 86400, 0.25, 1.0)
    assert pess < 1.0  # tiny size vs a huge target floor -> negligible reward


def test_reward_quotes_join_touch_scores_full_size():
    # At the real 0.001 tick, quotes join the best -> 0 ticks from best ->
    # full proximity (discount^0 = 1). This is the bug C1 fixed.
    q = reward_quotes("t", BOOK, capital_usd=300.0, tick_size=0.001)
    assert {x.side for x in q} == {"BUY", "SELL"}
    assert next(x for x in q if x.side == "BUY").price == 0.49   # at best_bid
    assert next(x for x in q if x.side == "SELL").price == 0.51  # at best_ask
    score = sum(x.size for x in q)  # discount^0 = 1 on both sides
    opt, _ = estimate_reward_range(q, BOOK, PARAMS, 0.001, 86400, 0.25, 1.0)
    assert opt > 0.0 and score == 2 * float(int(300.0 / 0.50))


def test_reward_quotes_size_from_capital():
    q = reward_quotes("t", BOOK, capital_usd=300.0, tick_size=0.001)
    assert next(x for x in q if x.side == "BUY").size == float(int(300.0 / 0.50))  # 600


def test_reward_quotes_ticks_behind_steps_off_best():
    q = reward_quotes("t", BOOK, 300.0, 0.001, ticks_behind=2)
    assert abs(next(x for x in q if x.side == "BUY").price - (0.49 - 0.002)) < 1e-9
    assert abs(next(x for x in q if x.side == "SELL").price - (0.51 + 0.002)) < 1e-9


def test_reward_quotes_skips_outside_band():
    assert reward_quotes("t", {"best_bid": 0.97, "best_ask": 0.99}, 300.0, 0.001) == []


def test_reward_quotes_inventory_cap_suppresses_buy_when_long():
    q = reward_quotes("t", BOOK, 300.0, 0.001, inventory_qty=100000)  # far over cap long
    assert all(x.side != "BUY" for x in q)
