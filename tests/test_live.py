import time
from polybot.analysis import live
from polybot.storage import verify_db

def _seed(conn, uid, settled, model_p, market_p, close_ts):
    verify_db.upsert_market(conn, {"market_uid": uid, "venue": "kalshi", "external_id": uid.split(":")[1],
        "city": "New York", "target_date": "2026-06-23", "bucket_lo": 75.0, "bucket_hi": 76.0,
        "unit": "F", "question": f"q {uid}", "close_ts": close_ts})
    verify_db.insert_quote(conn, uid, time.time(), market_p, market_p-0.02, market_p+0.02)
    verify_db.insert_pred(conn, uid, time.time(), model_p, 24.0)
    if settled:
        verify_db.settle_market(conn, uid, 1)

def test_current_disagreements_ranks_by_abs_edge_and_excludes_settled(tmp_path):
    conn = verify_db.connect(str(tmp_path / "v.sqlite3"))
    future = time.time() + 24*3600
    _seed(conn, "kalshi:A", False, model_p=0.80, market_p=0.50, close_ts=future)  # edge +0.30
    _seed(conn, "kalshi:B", False, model_p=0.40, market_p=0.45, close_ts=future)  # edge -0.05
    _seed(conn, "kalshi:C", True,  model_p=0.90, market_p=0.10, close_ts=future)  # settled -> excluded
    rows = live.current_disagreements(conn, limit=10)
    assert [r["market_uid"] for r in rows] == ["kalshi:A", "kalshi:B"]  # A first (bigger |edge|), C excluded
    assert rows[0]["edge"] == 0.30 and rows[0]["model_prob"] == 0.80 and rows[0]["market_prob"] == 0.50
    assert rows[0]["lead_hours"] is not None and rows[0]["lead_hours"] >= 0

def test_current_disagreements_skips_markets_missing_a_side(tmp_path):
    conn = verify_db.connect(str(tmp_path / "v.sqlite3"))
    future = time.time() + 24*3600
    verify_db.upsert_market(conn, {"market_uid": "kalshi:D", "venue": "kalshi", "external_id": "D",
        "city": "NYC", "target_date": "2026-06-23", "bucket_lo": 75.0, "bucket_hi": 76.0,
        "unit": "F", "question": "q", "close_ts": future})
    verify_db.insert_pred(conn, "kalshi:D", time.time(), 0.7, 24.0)  # model only, no quote
    assert live.current_disagreements(conn) == []

def test_tracking_summary_counts(tmp_path):
    conn = verify_db.connect(str(tmp_path / "v.sqlite3"))
    future = time.time() + 24*3600
    _seed(conn, "kalshi:A", False, 0.8, 0.5, future)
    _seed(conn, "kalshi:C", True, 0.9, 0.1, future)
    s = live.tracking_summary(conn)
    assert s["n_markets"] == 2 and s["n_open"] == 1 and s["n_settled"] == 1
    assert s["n_quotes"] == 2 and s["n_preds"] == 2 and s["n_cities"] == 1
    assert s["last_snapshot_ts"] is not None
