"""Score model-implied vs. market-implied probabilities against settled outcomes.

Pure functions (brier/log_loss/calibration_curve) plus DB-backed joins. The
evaluation frame pairs, for each settled market and target lead time, the model
and market probability snapshots nearest that lead time with the realized outcome.
"""
import math
import sqlite3

def brier(prob: float, outcome: int) -> float:
    return (prob - outcome) ** 2

def log_loss(prob: float, outcome: int, eps: float = 1e-9) -> float:
    p = min(max(prob, eps), 1 - eps)
    return -(outcome * math.log(p) + (1 - outcome) * math.log(1 - p))

def calibration_curve(pairs: list[tuple[float, int]], bins: int = 10) -> list[dict]:
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        sel = [(p, o) for p, o in pairs if (lo <= p < hi or (i == bins - 1 and p == 1.0))]
        n = len(sel)
        out.append({
            "bin": f"{lo:.1f}-{hi:.1f}", "n": n,
            "avg_prob": round(sum(p for p, _ in sel) / n, 4) if n else None,
            "win_rate": round(sum(o for _, o in sel) / n, 4) if n else None,
        })
    return out

def _nearest_snapshot(conn, table: str, value_col: str, market_uid: str, target_ts: float,
                      max_gap_s: float = 12 * 3600):
    rows = conn.execute(
        f"SELECT ts, {value_col} AS v FROM {table} WHERE market_uid = ?", (market_uid,)
    ).fetchall()
    if not rows:
        return None
    best = min(rows, key=lambda r: abs(r["ts"] - target_ts))
    if abs(best["ts"] - target_ts) > max_gap_s:
        return None
    return best["v"]

def evaluation_frame(conn: sqlite3.Connection,
                     lead_buckets: tuple[int, ...] = (72, 48, 24, 6),
                     max_gap_s: float = 12 * 3600) -> list[dict]:
    frame = []
    markets = conn.execute(
        "SELECT market_uid, city, close_ts, outcome FROM vmarket WHERE settled = 1"
    ).fetchall()
    for m in markets:
        for lead in lead_buckets:
            target_ts = m["close_ts"] - lead * 3600
            model_p = _nearest_snapshot(conn, "vpred", "model_prob", m["market_uid"], target_ts,
                                        max_gap_s=max_gap_s)
            market_p = _nearest_snapshot(conn, "vquote", "market_prob", m["market_uid"], target_ts,
                                         max_gap_s=max_gap_s)
            if model_p is None or market_p is None:
                continue
            frame.append({
                "market_uid": m["market_uid"], "city": m["city"], "lead_hours": lead,
                "model_prob": model_p, "market_prob": market_p, "outcome": int(m["outcome"]),
            })
    return frame

def score_by_lead_time(conn: sqlite3.Connection,
                       lead_buckets: tuple[int, ...] = (72, 48, 24, 6),
                       max_gap_s: float = 12 * 3600) -> list[dict]:
    frame = evaluation_frame(conn, lead_buckets, max_gap_s=max_gap_s)
    out = []
    for lead in lead_buckets:
        rows = [r for r in frame if r["lead_hours"] == lead]
        if not rows:
            continue
        n = len(rows)
        out.append({
            "lead_hours": lead, "n": n,
            "model_brier": round(sum(brier(r["model_prob"], r["outcome"]) for r in rows) / n, 4),
            "market_brier": round(sum(brier(r["market_prob"], r["outcome"]) for r in rows) / n, 4),
            "model_logloss": round(sum(log_loss(r["model_prob"], r["outcome"]) for r in rows) / n, 4),
            "market_logloss": round(sum(log_loss(r["market_prob"], r["outcome"]) for r in rows) / n, 4),
        })
    return out
