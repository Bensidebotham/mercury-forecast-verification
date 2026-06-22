"""Unified cross-venue store for the forecast-verification pipeline.

Separate DB file from the legacy trading store so nothing here depends on
trading code. Raw sqlite3 to match the existing project style.
"""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS vmarket (
    market_uid  TEXT PRIMARY KEY,   -- f"{venue}:{external_id}"
    venue       TEXT,               -- kalshi | polymarket
    external_id TEXT,               -- kalshi ticker | polymarket token_id
    city        TEXT,
    target_date TEXT,               -- YYYY-MM-DD local to the city
    bucket_lo   REAL,               -- NULL = open-ended below
    bucket_hi   REAL,               -- NULL = open-ended above
    unit        TEXT,
    question    TEXT,
    close_ts    REAL,
    settled     INTEGER DEFAULT 0,
    outcome     INTEGER             -- 1 = YES resolved true, 0 = false
);
CREATE TABLE IF NOT EXISTS vquote (
    ts          REAL,
    market_uid  TEXT,
    market_prob REAL,               -- implied P(YES) in [0,1]
    best_bid    REAL,
    best_ask    REAL
);
CREATE INDEX IF NOT EXISTS idx_vquote ON vquote(market_uid, ts);
CREATE TABLE IF NOT EXISTS vpred (
    ts          REAL,
    market_uid  TEXT,
    model_prob  REAL,               -- model P(YES) in [0,1]
    lead_hours  REAL                -- hours before close_ts at capture
);
CREATE INDEX IF NOT EXISTS idx_vpred ON vpred(market_uid, ts);
"""

def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn

def upsert_market(conn: sqlite3.Connection, m: dict) -> None:
    conn.execute(
        """INSERT INTO vmarket (market_uid, venue, external_id, city, target_date,
                                bucket_lo, bucket_hi, unit, question, close_ts)
           VALUES (:market_uid, :venue, :external_id, :city, :target_date,
                   :bucket_lo, :bucket_hi, :unit, :question, :close_ts)
           ON CONFLICT(market_uid) DO UPDATE SET close_ts = :close_ts, question = :question""",
        m,
    )
    conn.commit()

def insert_quote(conn, market_uid: str, ts: float, market_prob: float,
                 best_bid: float | None, best_ask: float | None) -> None:
    conn.execute("INSERT INTO vquote VALUES (?,?,?,?,?)",
                 (ts, market_uid, market_prob, best_bid, best_ask))
    conn.commit()

def insert_pred(conn, market_uid: str, ts: float, model_prob: float, lead_hours: float) -> None:
    conn.execute("INSERT INTO vpred VALUES (?,?,?,?)", (ts, market_uid, model_prob, lead_hours))
    conn.commit()

def settle_market(conn, market_uid: str, outcome: int) -> None:
    conn.execute("UPDATE vmarket SET settled = 1, outcome = ? WHERE market_uid = ?",
                 (outcome, market_uid))
    conn.commit()
