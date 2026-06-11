"""SQLite persistence — same lightweight approach as PropEdge.

Tables:
  markets        — discovered weather markets + token ids + resolution source
  book_snapshots — ts, token_id, best_bid/ask, mid, spread, depth json
  forecasts      — ts, station, source, horizon, members json
  model_probs    — ts, market, bucket, probability
  paper_fills    — ts, order details, fill price, pnl
"""

import sqlite3
from pathlib import Path


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """TODO(phase 1): create tables above (idempotent CREATE IF NOT EXISTS)."""
    raise NotImplementedError
