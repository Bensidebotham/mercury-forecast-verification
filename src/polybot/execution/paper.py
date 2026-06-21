"""Paper execution engine.

Simulates taker fills and resting maker orders against live books.
Conservative fill model:
  - taker: fills immediately at the touch, capped by displayed depth
  - maker: a resting BUY at price b fills only when the live best ask
    drops to <= b (someone actually crossed), haircut by
    maker_fill_haircut to avoid flattering ourselves about queue
    position. SELLs mirror. Fees use the Polymarket US curve.
Settlement pays $1/0 per contract when the market resolves; every fill
stores model_prob so the calibration report can score the model later.
"""

import sqlite3
import time

from polybot.config import QuotingConfig
from polybot.fees import trade_fee
from polybot.strategy.maker import Quote
from polybot.strategy.signals import TakerSignal


def _position(conn: sqlite3.Connection, token_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM positions WHERE token_id = ?", (token_id,)
    ).fetchone()


def position_qty(conn: sqlite3.Connection, token_id: str) -> float:
    row = _position(conn, token_id)
    return row["qty"] if row else 0.0


def _apply_fill(
    conn: sqlite3.Connection,
    token_id: str,
    side: str,
    price: float,
    size: float,
    fee: float,
    kind: str,
    order_id: int | None,
    model_prob: float | None,
) -> None:
    conn.execute(
        "INSERT INTO paper_fills (ts, order_id, token_id, side, kind, price, size, fee, model_prob)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (time.time(), order_id, token_id, side, kind, price, size, fee, model_prob),
    )
    row = _position(conn, token_id)
    qty, avg_cost, realized = (
        (row["qty"], row["avg_cost"], row["realized_pnl"]) if row else (0.0, 0.0, 0.0)
    )
    if side == "BUY":
        new_qty = qty + size
        avg_cost = (qty * avg_cost + size * price) / new_qty if new_qty else 0.0
        qty = new_qty
    else:  # SELL closes long inventory
        close = min(size, qty)
        realized += close * (price - avg_cost)
        qty -= close
        if qty == 0:
            avg_cost = 0.0
    realized -= fee
    conn.execute(
        "INSERT INTO positions (token_id, qty, avg_cost, realized_pnl) VALUES (?,?,?,?)"
        " ON CONFLICT(token_id) DO UPDATE SET qty=?, avg_cost=?, realized_pnl=?",
        (token_id, qty, avg_cost, realized, qty, avg_cost, realized),
    )
    conn.commit()


def execute_taker(conn: sqlite3.Connection, sig: TakerSignal, cfg: QuotingConfig) -> None:
    fee = trade_fee(cfg.taker_theta, sig.size, sig.price)
    cur = conn.execute(
        "INSERT INTO paper_orders (ts, token_id, side, kind, price, size, status, filled_size, model_prob)"
        " VALUES (?,?,?,?,?,?, 'filled', ?, ?)",
        (time.time(), sig.token_id, sig.side, "taker", sig.price, sig.size, sig.size, sig.model_prob),
    )
    _apply_fill(
        conn, sig.token_id, sig.side, sig.price, sig.size, fee, "taker", cur.lastrowid, sig.model_prob
    )


def refresh_maker_orders(
    conn: sqlite3.Connection, token_id: str, quotes: list[Quote], model_prob: float
) -> None:
    """Cancel-and-replace: open maker orders for this token are replaced
    by the new quote set each cycle (mirrors live cancel/repost flow)."""
    conn.execute(
        "UPDATE paper_orders SET status='cancelled'"
        " WHERE token_id=? AND kind='maker' AND status='open'",
        (token_id,),
    )
    for q in quotes:
        conn.execute(
            "INSERT INTO paper_orders (ts, token_id, side, kind, price, size, model_prob)"
            " VALUES (?,?,?,?,?,?,?)",
            (time.time(), q.token_id, q.side, "maker", q.price, q.size, model_prob),
        )
    conn.commit()


def check_maker_fills(conn: sqlite3.Connection, token_id: str, book: dict, cfg: QuotingConfig) -> int:
    """Fill resting orders the live book has crossed. Returns fill count."""
    fills = 0
    open_orders = conn.execute(
        "SELECT * FROM paper_orders WHERE token_id=? AND kind='maker' AND status='open'",
        (token_id,),
    ).fetchall()
    for o in open_orders:
        filled = 0.0
        if o["side"] == "BUY" and book.get("best_ask") is not None and book["best_ask"] <= o["price"]:
            filled = min(o["size"], book.get("ask_depth", 0) * cfg.maker_fill_haircut)
        elif o["side"] == "SELL" and book.get("best_bid") is not None and book["best_bid"] >= o["price"]:
            filled = min(o["size"], book.get("bid_depth", 0) * cfg.maker_fill_haircut)
        filled = float(int(filled))
        if filled >= 1:
            fee = trade_fee(cfg.maker_theta, filled, o["price"])  # negative = rebate
            conn.execute(
                "UPDATE paper_orders SET status='filled', filled_size=? WHERE id=?",
                (filled, o["id"]),
            )
            _apply_fill(
                conn, token_id, o["side"], o["price"], filled, fee, "maker", o["id"], o["model_prob"]
            )
            fills += 1
    return fills


def settle_market(conn: sqlite3.Connection, token_id: str, outcome: int) -> float:
    """Pay out $1 per contract if YES won, $0 otherwise. Returns PnL."""
    row = _position(conn, token_id)
    if row is None or row["qty"] == 0:
        conn.execute(
            "INSERT OR IGNORE INTO settlements VALUES (?,?,?,?,?)",
            (token_id, time.time(), outcome, 0.0, 0.0),
        )
        conn.commit()
        return 0.0
    qty, avg_cost = row["qty"], row["avg_cost"]
    pnl = qty * ((1.0 if outcome == 1 else 0.0) - avg_cost)
    conn.execute(
        "INSERT OR REPLACE INTO settlements VALUES (?,?,?,?,?)",
        (token_id, time.time(), outcome, qty, pnl),
    )
    conn.execute(
        "UPDATE positions SET qty=0, avg_cost=0, realized_pnl=realized_pnl+? WHERE token_id=?",
        (pnl, token_id),
    )
    conn.execute(
        "UPDATE paper_orders SET status='cancelled' WHERE token_id=? AND status='open'",
        (token_id,),
    )
    conn.commit()
    return pnl


def total_open_cost(conn: sqlite3.Connection) -> float:
    """Live capital at work, marked to market — the global bankroll guard.

    Uses the latest best_bid (what we could actually realize), NOT cost
    basis: positions that have decayed to ~0 (dead lottery tickets that
    haven't settled yet) shouldn't lock out new trading. Falls back to
    cost basis when no book snapshot exists yet.
    """
    rows = conn.execute(
        """SELECT p.qty, p.avg_cost,
                  (SELECT best_bid FROM book_snapshots b
                   WHERE b.token_id = p.token_id ORDER BY ts DESC LIMIT 1) AS bid
           FROM positions p WHERE p.qty > 0"""
    ).fetchall()
    total = 0.0
    for r in rows:
        mark = r["bid"] if r["bid"] is not None else r["avg_cost"]
        total += r["qty"] * mark
    return total


def event_exposure(conn: sqlite3.Connection, token_ids: list[str]) -> float:
    """Total cost basis currently at risk across one event's buckets."""
    if not token_ids:
        return 0.0
    marks = ",".join("?" * len(token_ids))
    row = conn.execute(
        f"SELECT COALESCE(SUM(qty*avg_cost),0) AS c FROM positions WHERE token_id IN ({marks})",
        token_ids,
    ).fetchone()
    return row["c"]
