"""SQLite persistence — same lightweight approach as PropEdge."""

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    token_id      TEXT PRIMARY KEY,   -- YES outcome token
    event_slug    TEXT,
    city          TEXT,
    target_date   TEXT,               -- YYYY-MM-DD local to the city
    question      TEXT,
    bucket_lo     REAL,               -- NULL = open-ended below
    bucket_hi     REAL,               -- NULL = open-ended above
    unit          TEXT,
    end_ts        REAL,
    closed        INTEGER DEFAULT 0,
    outcome       INTEGER             -- NULL until settled; 1 = YES won
);
CREATE TABLE IF NOT EXISTS book_snapshots (
    ts        REAL,
    token_id  TEXT,
    best_bid  REAL,
    best_ask  REAL,
    bid_depth REAL,
    ask_depth REAL,
    raw       TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap ON book_snapshots(token_id, ts);
CREATE TABLE IF NOT EXISTS forecasts (
    ts          REAL,
    city        TEXT,
    source      TEXT,
    target_date TEXT,
    members     TEXT                 -- JSON list of predicted daily highs
);
CREATE TABLE IF NOT EXISTS observations (
    ts          REAL,
    city        TEXT,
    target_date TEXT,
    obs_max     REAL
);
CREATE TABLE IF NOT EXISTS model_probs (
    ts       REAL,
    token_id TEXT,
    prob     REAL,
    obs_max  REAL
);
CREATE TABLE IF NOT EXISTS paper_orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL,
    token_id    TEXT,
    side        TEXT,                -- BUY | SELL (of the YES token)
    kind        TEXT,                -- taker | maker
    price       REAL,
    size        REAL,
    status      TEXT DEFAULT 'open', -- open | filled | cancelled
    filled_size REAL DEFAULT 0,
    model_prob  REAL
);
CREATE TABLE IF NOT EXISTS paper_fills (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       REAL,
    order_id INTEGER,
    token_id TEXT,
    side     TEXT,
    kind     TEXT,
    price    REAL,
    size     REAL,
    fee      REAL,                   -- negative = rebate received
    model_prob REAL
);
CREATE TABLE IF NOT EXISTS positions (
    token_id     TEXT PRIMARY KEY,
    qty          REAL DEFAULT 0,     -- signed; + = long YES
    avg_cost     REAL DEFAULT 0,
    realized_pnl REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settlements (
    token_id TEXT PRIMARY KEY,
    ts       REAL,
    outcome  INTEGER,
    qty      REAL,
    pnl      REAL
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    ts         REAL,
    realized   REAL,
    unrealized REAL,
    equity     REAL
);
CREATE TABLE IF NOT EXISTS maker_rewards (
    ts         REAL,
    token_id   TEXT,
    est_reward REAL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_market(conn: sqlite3.Connection, m: dict) -> None:
    conn.execute(
        """INSERT INTO markets (token_id, event_slug, city, target_date, question,
                                bucket_lo, bucket_hi, unit, end_ts, closed)
           VALUES (:token_id, :event_slug, :city, :target_date, :question,
                   :bucket_lo, :bucket_hi, :unit, :end_ts, :closed)
           ON CONFLICT(token_id) DO UPDATE SET closed = :closed""",
        m,
    )
    conn.commit()


def insert_snapshot(conn: sqlite3.Connection, token_id: str, book: dict) -> None:
    conn.execute(
        "INSERT INTO book_snapshots VALUES (?,?,?,?,?,?,?)",
        (
            time.time(),
            token_id,
            book.get("best_bid"),
            book.get("best_ask"),
            book.get("bid_depth"),
            book.get("ask_depth"),
            json.dumps({"bids": book.get("bids", [])[:5], "asks": book.get("asks", [])[:5]}),
        ),
    )
    conn.commit()


def insert_forecast(conn, city: str, source: str, target_date: str, members: list[float]) -> None:
    conn.execute(
        "INSERT INTO forecasts VALUES (?,?,?,?,?)",
        (time.time(), city, source, target_date, json.dumps(members)),
    )
    conn.commit()


def insert_observation(conn, city: str, target_date: str, obs_max: float) -> None:
    conn.execute(
        "INSERT INTO observations VALUES (?,?,?,?)",
        (time.time(), city, target_date, obs_max),
    )
    conn.commit()


def insert_model_prob(conn, token_id: str, prob: float, obs_max: float | None) -> None:
    conn.execute(
        "INSERT INTO model_probs VALUES (?,?,?,?)", (time.time(), token_id, prob, obs_max)
    )
    conn.commit()
