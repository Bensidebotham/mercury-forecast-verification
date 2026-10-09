"""Live (pre-settlement) views: where the model currently disagrees with the market,
plus a tracking summary. Uses the latest snapshot per open market so the dashboard
shows real signal before any market settles."""
import sqlite3
import time


def _latest(conn: sqlite3.Connection, table: str, col: str, market_uid: str):
    row = conn.execute(
        f"SELECT {col} AS v, ts FROM {table} WHERE market_uid=? ORDER BY ts DESC LIMIT 1",
        (market_uid,),
    ).fetchone()
    return (row["v"], row["ts"]) if row else (None, None)


def current_disagreements(conn: sqlite3.Connection, limit: int = 25, now: float | None = None, min_lead_hours: float = 1.0) -> list[dict]:
    now = now if now is not None else time.time()
    out = []
    markets = conn.execute(
        "SELECT market_uid, venue, city, target_date, question, bucket_lo, bucket_hi, close_ts "
        "FROM vmarket WHERE settled=0"
    ).fetchall()
    for m in markets:
        market_p, _ = _latest(conn, "vquote", "market_prob", m["market_uid"])
        model_p, _ = _latest(conn, "vpred", "model_prob", m["market_uid"])
        if market_p is None or model_p is None:
            continue
        lead_h = (m["close_ts"] - now) / 3600.0 if m["close_ts"] is not None else None
        if lead_h is None or lead_h < min_lead_hours:
            continue
        out.append({
            "market_uid": m["market_uid"], "venue": m["venue"], "city": m["city"],
            "target_date": m["target_date"], "question": m["question"],
            "bucket_lo": m["bucket_lo"], "bucket_hi": m["bucket_hi"],
            "model_prob": round(model_p, 4), "market_prob": round(market_p, 4),
            "edge": round(model_p - market_p, 4),
            "lead_hours": round(lead_h, 1),
        })
    out.sort(key=lambda r: abs(r["edge"]), reverse=True)
    return out[:limit]


def tracking_summary(conn: sqlite3.Connection) -> dict:
    one = lambda q: conn.execute(q).fetchone()[0]
    return {
        "n_markets": one("SELECT COUNT(*) FROM vmarket"),
        "n_open": one("SELECT COUNT(*) FROM vmarket WHERE settled=0"),
        "n_settled": one("SELECT COUNT(*) FROM vmarket WHERE settled=1"),
        "n_quotes": one("SELECT COUNT(*) FROM vquote"),
        "n_preds": one("SELECT COUNT(*) FROM vpred"),
        "n_cities": one("SELECT COUNT(DISTINCT city) FROM vmarket"),
        "last_snapshot_ts": one("SELECT MAX(ts) FROM vpred"),
    }
