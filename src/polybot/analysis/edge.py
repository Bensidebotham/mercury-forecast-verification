"""Reporting: paper PnL, fill quality, and model calibration.

Calibration is the gate for real money: until model probabilities are
demonstrably honest (Brier/bins), paper profits could be luck.
"""

import sqlite3


def pnl_report(conn: sqlite3.Connection) -> dict:
    realized = conn.execute(
        "SELECT COALESCE(SUM(realized_pnl),0) AS v FROM positions"
    ).fetchone()["v"]
    open_pos = conn.execute(
        """SELECT p.token_id, p.qty, p.avg_cost, m.question,
                  (SELECT best_bid FROM book_snapshots b WHERE b.token_id = p.token_id
                   ORDER BY ts DESC LIMIT 1) AS mark
           FROM positions p LEFT JOIN markets m ON m.token_id = p.token_id
           WHERE p.qty != 0"""
    ).fetchall()
    unrealized = sum(
        r["qty"] * ((r["mark"] or r["avg_cost"]) - r["avg_cost"]) for r in open_pos
    )
    fills = conn.execute(
        """SELECT kind, COUNT(*) AS n, COALESCE(SUM(size),0) AS contracts,
                  COALESCE(SUM(fee),0) AS fees
           FROM paper_fills GROUP BY kind"""
    ).fetchall()
    settlements = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(pnl),0) AS pnl FROM settlements WHERE qty != 0"
    ).fetchone()
    return {
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "open_positions": [dict(r) for r in open_pos],
        "fills_by_kind": [dict(r) for r in fills],
        "settlements": dict(settlements),
    }


def calibration_report(conn: sqlite3.Connection, bins: int = 10) -> list[dict]:
    """Bin every traded model_prob against the settled outcome.

    A calibrated model has avg_prob ~= win_rate per bin. Brier score
    summarizes; this only becomes meaningful after dozens of settlements.
    """
    rows = conn.execute(
        """SELECT f.model_prob AS prob, s.outcome AS outcome
           FROM paper_fills f JOIN settlements s ON s.token_id = f.token_id
           WHERE f.model_prob IS NOT NULL AND f.side = 'BUY'"""
    ).fetchall()
    if not rows:
        return []
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        in_bin = [r for r in rows if lo <= r["prob"] < hi or (b == bins - 1 and r["prob"] == 1.0)]
        if not in_bin:
            continue
        avg_p = sum(r["prob"] for r in in_bin) / len(in_bin)
        win = sum(r["outcome"] for r in in_bin) / len(in_bin)
        brier = sum((r["prob"] - r["outcome"]) ** 2 for r in in_bin) / len(in_bin)
        out.append(
            {"bin": f"{lo:.1f}-{hi:.1f}", "n": len(in_bin), "avg_prob": round(avg_p, 3),
             "win_rate": round(win, 3), "brier": round(brier, 4)}
        )
    return out


def spread_report(conn: sqlite3.Connection) -> list[dict]:
    """Measured spreads by price band — the phase-1 deliverable."""
    rows = conn.execute(
        """SELECT CASE
                    WHEN (best_bid+best_ask)/2 < 0.05 THEN '<0.05'
                    WHEN (best_bid+best_ask)/2 < 0.10 THEN '0.05-0.10'
                    WHEN (best_bid+best_ask)/2 < 0.30 THEN '0.10-0.30'
                    ELSE '0.30+'
                  END AS band,
                  COUNT(*) AS n,
                  AVG(best_ask-best_bid) AS avg_spread,
                  AVG((best_ask-best_bid)/((best_bid+best_ask)/2)) AS avg_rel_spread
           FROM book_snapshots
           WHERE best_bid IS NOT NULL AND best_ask IS NOT NULL
           GROUP BY band ORDER BY band"""
    ).fetchall()
    return [dict(r) for r in rows]
