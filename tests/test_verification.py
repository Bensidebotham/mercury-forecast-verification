import math
import pytest
from polybot.analysis import verification as V
from polybot.storage import verify_db

def test_brier_and_log_loss():
    assert V.brier(0.7, 1) == pytest.approx(0.09)
    assert V.brier(0.7, 0) == pytest.approx(0.49)
    assert V.log_loss(0.8, 1) == pytest.approx(-math.log(0.8))

def test_calibration_curve_buckets_and_winrate():
    pairs = [(0.1, 0), (0.15, 0), (0.85, 1), (0.9, 1)]
    curve = V.calibration_curve(pairs, bins=2)
    lo, hi = curve[0], curve[-1]
    assert lo["n"] == 2 and lo["win_rate"] == 0.0
    assert hi["n"] == 2 and hi["win_rate"] == 1.0

def test_score_by_lead_time_compares_model_vs_market(tmp_path):
    conn = verify_db.connect(str(tmp_path / "v.sqlite3"))
    uid = "kalshi:T1"
    verify_db.upsert_market(conn, {
        "market_uid": uid, "venue": "kalshi", "external_id": "T1", "city": "NYC",
        "target_date": "2026-06-22", "bucket_lo": 75.0, "bucket_hi": 76.0, "unit": "F",
        "question": "q", "close_ts": 1000.0})
    verify_db.insert_quote(conn, uid, ts=1000.0 - 48*3600, market_prob=0.50, best_bid=0.48, best_ask=0.52)
    verify_db.insert_pred(conn, uid, ts=1000.0 - 48*3600, model_prob=0.80, lead_hours=48.0)
    verify_db.settle_market(conn, uid, outcome=1)  # YES happened; model was closer
    scored = V.score_by_lead_time(conn, lead_buckets=(48,))
    row = scored[0]
    assert row["lead_hours"] == 48 and row["n"] == 1
    assert row["model_brier"] < row["market_brier"]
