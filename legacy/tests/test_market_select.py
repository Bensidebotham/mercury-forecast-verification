from polybot.config import RewardsConfig
from polybot.model.market_select import MarketScore, score_market, select_markets

CFG = RewardsConfig()
NOW = 1_000_000.0
REWARD = {"pool_usd": 2000.0, "discount": 0.3, "target_size": 15000.0,
          "period": "live", "program_id": "p"}


def _snaps(mids, depth=100.0):
    # (ts, best_bid, best_ask, bid_depth, ask_depth)
    return [(NOW - i * 30, m - 0.01, m + 0.01, depth, depth) for i, m in enumerate(mids)]


def test_incentivized_market_with_book_is_eligible():
    s = score_market("m", _snaps([0.50, 0.50]), REWARD, NOW, CFG)
    assert isinstance(s, MarketScore)
    assert s.eligible is True
    assert s.attractiveness == 2000.0 / 15000.0


def test_no_reward_program_is_ineligible():
    s = score_market("m", _snaps([0.50, 0.50]), None, NOW, CFG)
    assert s.eligible is False


def test_no_book_is_ineligible():
    s = score_market("m", [], REWARD, NOW, CFG)  # no snapshots / no depth
    assert s.eligible is False


def test_volatility_is_reported_not_filtered():
    # A jumpy market is STILL eligible (we no longer filter on slowness);
    # the volatility is surfaced for reporting/attribution only.
    s = score_market("jumpy", _snaps([0.30, 0.60, 0.35, 0.58]), REWARD, NOW, CFG)
    assert s.midpoint_vol > 0.05
    assert s.eligible is True


def test_select_ranks_by_attractiveness_and_caps():
    rich = {**REWARD, "pool_usd": 5000.0, "target_size": 10000.0}  # density 0.5
    lean = {**REWARD, "pool_usd": 1000.0, "target_size": 20000.0}  # density 0.05
    scored = [
        score_market("lean", _snaps([0.5, 0.5]), lean, NOW, CFG),
        score_market("rich", _snaps([0.5, 0.5]), rich, NOW, CFG),
        score_market("dead", _snaps([0.5, 0.5]), None, NOW, CFG),  # ineligible
    ]
    assert select_markets(scored, max_markets=1) == ["rich"]
    assert select_markets(scored, max_markets=5) == ["rich", "lean"]
