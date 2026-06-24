import pyarrow.parquet as pq
from polybot.pipeline.export import export_evaluation
from polybot.storage import verify_db

def test_export_writes_parquet(tmp_path):
    conn = verify_db.connect(str(tmp_path / "v.sqlite3"))
    uid = "kalshi:T1"
    verify_db.upsert_market(conn, {"market_uid": uid, "venue": "kalshi", "external_id": "T1",
        "city": "NYC", "target_date": "2026-06-22", "bucket_lo": 75.0, "bucket_hi": 76.0,
        "unit": "F", "question": "q", "close_ts": 1000.0})
    verify_db.insert_quote(conn, uid, 1000.0 - 48*3600, 0.5, 0.48, 0.52)
    verify_db.insert_pred(conn, uid, 1000.0 - 48*3600, 0.8, 48.0)
    verify_db.settle_market(conn, uid, 1)
    out = tmp_path / "evaluations.parquet"
    n = export_evaluation(conn, str(out), lead_buckets=(48,))
    assert n == 1
    assert pq.read_table(str(out)).num_rows == 1

import json
from polybot.pipeline.export import export_json

def test_export_json_includes_live_sections(tmp_path):
    import json, time
    from polybot.pipeline.export import export_json
    from polybot.storage import verify_db
    conn = verify_db.connect(str(tmp_path / "v.sqlite3"))
    future = time.time() + 24*3600
    verify_db.upsert_market(conn, {"market_uid": "kalshi:A", "venue": "kalshi", "external_id": "A",
        "city": "New York", "target_date": "2026-06-23", "bucket_lo": 75.0, "bucket_hi": 76.0,
        "unit": "F", "question": "q", "close_ts": future})
    verify_db.insert_quote(conn, "kalshi:A", time.time(), 0.5, 0.48, 0.52)
    verify_db.insert_pred(conn, "kalshi:A", time.time(), 0.8, 24.0)
    out = tmp_path / "e.json"
    export_json(conn, str(out))
    doc = json.loads(out.read_text())
    assert doc["tracking"]["n_open"] == 1
    assert len(doc["live_disagreements"]) == 1
    assert doc["live_disagreements"][0]["edge"] == 0.3

def test_export_json_shape(tmp_path):
    from polybot.storage import verify_db
    conn = verify_db.connect(str(tmp_path / "v.sqlite3"))
    uid = "kalshi:T1"
    verify_db.upsert_market(conn, {"market_uid": uid, "venue": "kalshi", "external_id": "T1",
        "city": "NYC", "target_date": "2026-06-22", "bucket_lo": 75.0, "bucket_hi": 76.0,
        "unit": "F", "question": "q", "close_ts": 1000.0})
    verify_db.insert_quote(conn, uid, 1000.0 - 48*3600, 0.5, 0.48, 0.52)
    verify_db.insert_pred(conn, uid, 1000.0 - 48*3600, 0.8, 48.0)
    verify_db.settle_market(conn, uid, 1)
    out = tmp_path / "evaluations.json"
    export_json(conn, str(out), lead_buckets=(48,))
    doc = json.loads(out.read_text())
    assert doc["n_resolved"] == 1
    assert {"lead_hours", "model_brier", "market_brier", "n"} <= set(doc["by_lead"][0])
    assert {"city", "model_prob", "market_prob", "outcome", "lead_hours"} <= set(doc["rows"][0])
    assert "generated_ts" in doc
