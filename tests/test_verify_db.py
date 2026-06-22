from polybot.storage import verify_db

def test_upsert_market_and_quote_and_pred(tmp_path):
    conn = verify_db.connect(str(tmp_path / "v.sqlite3"))
    verify_db.upsert_market(conn, {
        "market_uid": "kalshi:KXHIGHNY-26JUN22-B75", "venue": "kalshi",
        "external_id": "KXHIGHNY-26JUN22-B75", "city": "New York", "target_date": "2026-06-22",
        "bucket_lo": 75.0, "bucket_hi": 76.0, "unit": "F",
        "question": "NYC high 75-76F?", "close_ts": 1_000_000.0,
    })
    verify_db.insert_quote(conn, "kalshi:KXHIGHNY-26JUN22-B75", ts=10.0,
                           market_prob=0.42, best_bid=0.40, best_ask=0.44)
    verify_db.insert_pred(conn, "kalshi:KXHIGHNY-26JUN22-B75", ts=10.0,
                          model_prob=0.55, lead_hours=48.0)
    verify_db.settle_market(conn, "kalshi:KXHIGHNY-26JUN22-B75", outcome=1)

    rows = conn.execute("SELECT settled, outcome FROM vmarket").fetchall()
    assert rows[0]["settled"] == 1 and rows[0]["outcome"] == 1
    assert conn.execute("SELECT market_prob FROM vquote").fetchone()["market_prob"] == 0.42
    assert conn.execute("SELECT lead_hours FROM vpred").fetchone()["lead_hours"] == 48.0
