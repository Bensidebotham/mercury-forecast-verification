from polybot.strategy.market_maker import MMQuote, estimate_reward_range

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
