from polybot.storage import db

ROW = {
    "token_id": "dota-x", "event_slug": "", "category": "sports",
    "question": "GL vs AAI", "end_ts": 1000.0, "closed": False, "tick_size": 0.01,
    "reward": {"pool_usd": 2000.0, "discount": 0.3, "target_size": 15000.0,
               "period": "live", "program_id": "dota2_ml_live"},
}


def test_upsert_reward_market_and_read_back():
    conn = db.connect(":memory:")
    db.upsert_reward_market(conn, ROW)
    got = conn.execute("SELECT * FROM reward_markets WHERE token_id='dota-x'").fetchone()
    assert got["category"] == "sports"
    assert got["pool_usd"] == 2000.0
    assert got["program_id"] == "dota2_ml_live"
    assert got["period"] == "live"
    assert got["tick_size"] == 0.01


def test_upsert_reward_market_handles_none_reward():
    conn = db.connect(":memory:")
    db.upsert_reward_market(conn, {**ROW, "token_id": "nr", "reward": None})
    got = conn.execute("SELECT * FROM reward_markets WHERE token_id='nr'").fetchone()
    assert got["pool_usd"] is None
    assert got["category"] == "sports"


def test_insert_reward_estimate():
    conn = db.connect(":memory:")
    db.insert_reward_estimate(conn, "dota-x", est_opt=2.5, est_pess=0.8)
    got = conn.execute("SELECT * FROM reward_estimates WHERE token_id='dota-x'").fetchone()
    assert got["est_opt"] == 2.5
    assert got["est_pess"] == 0.8
