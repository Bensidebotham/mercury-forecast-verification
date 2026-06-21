from polybot.model.calibration import _isotonic, apply_calibration, fit_calibration
from polybot.storage import db


def test_isotonic_enforces_monotone():
    pts = [(0.05, 0.0, 100), (0.15, 0.0, 100), (0.25, 0.6, 50), (0.35, 0.4, 50)]
    out = _isotonic(pts)
    ys = [y for _, y in out]
    assert ys == sorted(ys)  # non-decreasing after pooling


def test_apply_identity_when_no_mapping():
    assert apply_calibration(0.3, None) == 0.3


def test_apply_shrinks_overconfident_low_probs():
    # learned: 0.05->0, 0.35->0.4
    mapping = [(0.05, 0.0), (0.35, 0.4)]
    assert apply_calibration(0.05, mapping) == 0.0
    assert apply_calibration(0.14, mapping) < 0.14  # overconfident -> shrunk
    assert abs(apply_calibration(0.35, mapping) - 0.4) < 1e-9


def test_fit_returns_none_below_min_samples(tmp_path):
    conn = db.connect(str(tmp_path / "c.sqlite3"))
    assert fit_calibration(conn) is None


def test_fit_learns_overconfidence(tmp_path):
    conn = db.connect(str(tmp_path / "c.sqlite3"))
    # 50 fills at model 0.12 that all lost; 50 at 0.35 that half won
    import time
    for i in range(50):
        conn.execute(
            "INSERT INTO paper_fills (ts, token_id, side, kind, price, size, fee, model_prob)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (time.time(), f"lo{i}", "BUY", "taker", 0.02, 10, 0, 0.12),
        )
        conn.execute("INSERT INTO settlements VALUES (?,?,?,?,?)", (f"lo{i}", time.time(), 0, 10, -1))
    for i in range(50):
        conn.execute(
            "INSERT INTO paper_fills (ts, token_id, side, kind, price, size, fee, model_prob)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (time.time(), f"hi{i}", "BUY", "taker", 0.30, 10, 0, 0.35),
        )
        conn.execute(
            "INSERT INTO settlements VALUES (?,?,?,?,?)", (f"hi{i}", time.time(), 1 if i % 2 else 0, 10, 1)
        )
    conn.commit()
    mapping = fit_calibration(conn)
    assert mapping is not None
    # a raw 0.12 should now map near 0 (it always lost)
    assert apply_calibration(0.12, mapping) < 0.05
    # a raw 0.35 should map near its real win rate ~0.5
    assert apply_calibration(0.35, mapping) > 0.3
