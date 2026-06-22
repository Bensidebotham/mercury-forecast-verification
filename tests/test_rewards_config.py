from polybot.config import RewardsConfig, load_settings


def test_rewards_config_defaults():
    c = RewardsConfig()
    assert c.capital_usd > 0
    assert c.max_markets >= 1
    assert c.discovery_limit >= c.max_markets  # fetch enough detail to fill max_markets
    assert c.min_snapshots >= 1
    assert 0 < c.opt_competitor_factor <= 1     # light competition (optimistic)
    assert c.pess_competitor_factor >= 1        # heavy competition (pessimistic)
    assert c.db_path.endswith(".sqlite3")


def test_settings_exposes_rewards():
    s = load_settings()
    assert isinstance(s.rewards, RewardsConfig)
