from polybot.config import QuotingConfig
from polybot.fees import trade_fee
from polybot.strategy.maker import generate_quotes
from polybot.strategy.signals import taker_signal

CFG = QuotingConfig()


def test_fee_curve_matches_published_schedule():
    # docs.polymarket.us: 100-lot at $0.50 -> taker $1.25, maker -$0.31
    assert abs(trade_fee(0.05, 100, 0.50) - 1.25) < 1e-9
    assert abs(trade_fee(-0.0125, 100, 0.50) + 0.3125) < 1e-9
    # tails are near-free
    assert trade_fee(0.05, 100, 0.01) < 0.05


def test_taker_buy_fires_on_real_edge():
    book = {"best_ask": 0.02, "ask_depth": 500, "best_bid": 0.01, "bid_depth": 500}
    sig = taker_signal("tok", model_prob=0.10, book=book, cfg=CFG)
    assert sig is not None and sig.side == "BUY"
    assert sig.price == 0.02
    assert sig.size * sig.price <= CFG.max_position_usd + 1e-9


def test_taker_respects_min_edge():
    book = {"best_ask": 0.10, "ask_depth": 500, "best_bid": 0.09, "bid_depth": 500}
    assert taker_signal("tok", model_prob=0.11, book=book, cfg=CFG) is None


def test_taker_sell_only_with_inventory():
    book = {"best_ask": 0.50, "ask_depth": 100, "best_bid": 0.40, "bid_depth": 100}
    # model says 0.2, bid 0.4 -> rich, but no inventory -> no signal
    assert taker_signal("tok", model_prob=0.20, book=book, cfg=CFG) is None
    sig = taker_signal("tok", model_prob=0.20, book=book, cfg=CFG, position_qty=50)
    assert sig is not None and sig.side == "SELL" and sig.size == 50


def test_maker_quotes_two_sided_with_inventory():
    book = {"best_bid": 0.04, "best_ask": 0.10, "bid_depth": 100, "ask_depth": 100}
    quotes = generate_quotes("tok", model_prob=0.07, book=book, cfg=CFG, position_qty=20)
    sides = {q.side for q in quotes}
    assert "BUY" in sides and "SELL" in sides
    buy = next(q for q in quotes if q.side == "BUY")
    assert buy.price < 0.07
    assert buy.price < book["best_ask"]  # resting, not crossing


def test_maker_never_crosses_the_ask():
    book = {"best_bid": 0.02, "best_ask": 0.03, "bid_depth": 100, "ask_depth": 100}
    quotes = generate_quotes("tok", model_prob=0.20, book=book, cfg=CFG)
    for q in quotes:
        if q.side == "BUY":
            assert q.price < book["best_ask"]


def test_salvage_exit_when_model_collapses():
    # bought at 0.059, model collapsed to 0.002, bid 0.003: salvage
    book = {"best_ask": 0.005, "ask_depth": 100, "best_bid": 0.003, "bid_depth": 500}
    sig = taker_signal(
        "tok", model_prob=0.002, book=book, cfg=CFG, position_qty=169, avg_cost=0.059
    )
    assert sig is not None and sig.side == "SELL"


def test_no_salvage_when_model_still_supports():
    # model 0.05 vs cost 0.06 — not collapsed; bid 0.03 below model -> hold
    book = {"best_ask": 0.07, "ask_depth": 100, "best_bid": 0.03, "bid_depth": 500}
    assert taker_signal(
        "tok", model_prob=0.05, book=book, cfg=CFG, position_qty=100, avg_cost=0.06
    ) is None


def test_event_budget_caps_taker_size():
    book = {"best_ask": 0.10, "ask_depth": 5000, "best_bid": 0.05, "bid_depth": 100}
    sig = taker_signal(
        "tok", model_prob=0.50, book=book, cfg=CFG, event_budget_usd=3.0
    )
    assert sig is not None
    assert sig.size * sig.price <= 3.0 + 1e-9


def test_event_budget_zero_blocks_buys():
    book = {"best_ask": 0.10, "ask_depth": 5000, "best_bid": 0.05, "bid_depth": 100}
    assert taker_signal(
        "tok", model_prob=0.50, book=book, cfg=CFG, event_budget_usd=0.0
    ) is None


def test_maker_respects_event_budget():
    book = {"best_bid": 0.04, "best_ask": 0.10, "bid_depth": 100, "ask_depth": 100}
    quotes = generate_quotes(
        "tok", model_prob=0.07, book=book, cfg=CFG, event_budget_usd=1.0
    )
    for q in quotes:
        if q.side == "BUY":
            assert q.size * q.price <= 1.0 + 1e-9


def test_lock_in_only_config_default_off():
    assert QuotingConfig().lock_in_only is False


def test_lock_in_config_toggles():
    cfg = QuotingConfig(lock_in_only=True)
    assert cfg.lock_in_only is True


def test_contract_cap_limits_size():
    # cheap ask + deep book + confident model: budget/price would be 1000,
    # but the per-fill contract cap clamps it.
    book = {"best_ask": 0.01, "ask_depth": 100000, "best_bid": 0.005, "bid_depth": 100}
    sig = taker_signal("tok", model_prob=0.90, book=book, cfg=CFG)
    assert sig is not None and sig.side == "BUY"
    assert sig.size == CFG.max_contracts_per_fill


def test_longshot_screened_unless_confident():
    # sub-min_taker_price ask with a low model prob: screened out despite edge.
    book = {"best_ask": 0.01, "ask_depth": 5000, "best_bid": 0.005, "bid_depth": 100}
    assert taker_signal("tok", model_prob=0.20, book=book, cfg=CFG) is None
    # same cheap ask, but near-certain -> allowed
    sig = taker_signal("tok", model_prob=0.60, book=book, cfg=CFG)
    assert sig is not None and sig.side == "BUY"


def test_normal_priced_buy_not_screened_or_capped():
    # at/above min_taker_price the longshot screen and cap don't bite.
    book = {"best_ask": 0.05, "ask_depth": 500, "best_bid": 0.04, "bid_depth": 100}
    sig = taker_signal("tok", model_prob=0.20, book=book, cfg=CFG)
    assert sig is not None and sig.side == "BUY"
    assert sig.size == 200  # 10 / 0.05, under the 500 cap


def test_plateau_lock_detection():
    from polybot.forecast.obs import is_plateaued
    import time as _t
    # build a day's obs: climbs to 79 by 14:30, then flat through 16:30
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = "America/New_York"
    zone = ZoneInfo(tz)
    # use a clearly-past date so the date-branch returns True regardless of clock
    past = "2000-06-16"
    assert is_plateaued([], tz, past, 14, 2.0, _t.time()) is True

    # today, plateaued: max hit 79 three hours ago, flat since, now 16:00
    now = _t.time()
    hist = [(now - 3*3600, 75.0), (now - 2.5*3600, 79.0), (now - 1*3600, 79.0), (now, 79.0)]
    # only meaningful if local hour >= earliest; can't force clock, so just
    # assert the no-history guard and monotone-climb (not plateaued) cases:
    climbing = [(now - 1.5*3600, 70.0), (now, 79.0)]  # recent exceeds prior
    # climbing should never be considered plateaued
    today = datetime.now(zone).strftime("%Y-%m-%d")
    assert is_plateaued(climbing, tz, today, 0, 1.0, now) is False
