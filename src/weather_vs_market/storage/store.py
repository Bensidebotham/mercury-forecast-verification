"""Unified cross-venue store: SQLite locally and in tests, Postgres (Neon) in CI.

One schema in SQLAlchemy Core so the same code runs on both. Snapshots are
append-only and idempotent: re-inserting the same (market, ts, source/model)
is a no-op, so a retried ingest run never double-counts.
"""
import json

from sqlalchemy import (
    Column, Engine, Float, Integer, MetaData, Table, Text, UniqueConstraint, create_engine,
    delete, func, select, update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

metadata = MetaData()

vmarket = Table(
    "vmarket", metadata,
    Column("market_uid", Text, primary_key=True),   # f"{venue}:{external_id}"
    Column("venue", Text, nullable=False),          # kalshi | polymarket
    Column("external_id", Text, nullable=False),    # kalshi ticker | polymarket YES token id
    Column("event_key", Text),                      # kalshi event ticker | polymarket event slug
    Column("city", Text, nullable=False),
    Column("station", Text),                        # settlement station for this venue
    Column("target_date", Text, nullable=False),    # YYYY-MM-DD local to the city
    Column("bucket_lo", Float),                     # NULL = open-ended below
    Column("bucket_hi", Float),                     # NULL = open-ended above
    Column("unit", Text),
    Column("question", Text),
    Column("close_ts", Float),
    Column("settled", Integer, nullable=False, server_default="0"),
    Column("outcome", Integer),                     # 1 = YES resolved true, 0 = false
)

vquote = Table(
    "vquote", metadata,
    Column("ts", Float, nullable=False),
    Column("market_uid", Text, nullable=False, index=True),
    Column("market_prob", Float, nullable=False),   # implied P(YES) in [0,1]
    Column("best_bid", Float),
    Column("best_ask", Float),
    Column("source", Text, nullable=False),         # live | kalshi_candles | polymarket_history
    UniqueConstraint("market_uid", "ts", "source"),
)

vpred = Table(
    "vpred", metadata,
    Column("ts", Float, nullable=False),
    Column("market_uid", Text, nullable=False, index=True),
    Column("model", Text, nullable=False),          # model name + version
    Column("model_prob", Float, nullable=False),    # model P(YES) in [0,1]
    Column("lead_hours", Float),                    # hours before close_ts at capture
    UniqueConstraint("market_uid", "ts", "model"),
)

ingest_run = Table(
    "ingest_run", metadata,
    Column("run_id", Text, primary_key=True),
    Column("started_ts", Float, nullable=False),
    Column("finished_ts", Float),
    Column("status", Text, nullable=False),         # ok | failed
    Column("n_markets", Integer), Column("n_quotes", Integer),
    Column("n_preds", Integer), Column("n_skipped", Integer),
    Column("detail", Text),                         # JSON: per-source counts and errors
)

published_result = Table(
    "published_result", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("generated_ts", Float, nullable=False),
    Column("doc", Text, nullable=False),            # the dashboard JSON document
)


def normalize_url(url: str) -> str:
    """Accept a Neon-style postgres URL, a SQLAlchemy URL, or a bare SQLite path."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    if "://" in url:
        return url
    return f"sqlite:///{url}"


def connect(url: str, schema: str | None = None) -> Engine:
    """Engine for `url`, with the schema created if missing.

    `schema` pins the Postgres search_path (used for per-test isolation).
    """
    url = normalize_url(url)
    kwargs = {}
    if url.startswith("sqlite"):
        from pathlib import Path
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    elif schema:
        kwargs["connect_args"] = {"options": f"-csearch_path={schema}"}
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    metadata.create_all(engine)
    return engine


def _insert(engine: Engine, table: Table):
    return (pg_insert if engine.dialect.name == "postgresql" else sqlite_insert)(table)


_MARKET_UPDATABLE = ("event_key", "station", "question", "close_ts")


def upsert_markets(engine: Engine, rows: list[dict]) -> None:
    """Insert markets, or refresh their metadata. Never touches settlement."""
    if not rows:
        return
    rows = [{c.name: r.get(c.name) for c in vmarket.columns if c.name not in ("settled", "outcome")}
            for r in rows]
    stmt = _insert(engine, vmarket)
    stmt = stmt.on_conflict_do_update(
        index_elements=["market_uid"],
        set_={c: stmt.excluded[c] for c in _MARKET_UPDATABLE},
    )
    with engine.begin() as c:
        c.execute(stmt, rows)


def _insert_ignore(engine: Engine, table: Table, rows: list[dict]) -> None:
    if not rows:
        return
    rows = [{c.name: r.get(c.name) for c in table.columns} for r in rows]
    with engine.begin() as c:
        c.execute(_insert(engine, table).on_conflict_do_nothing(), rows)


def insert_quotes(engine: Engine, rows: list[dict]) -> None:
    _insert_ignore(engine, vquote, rows)


def insert_preds(engine: Engine, rows: list[dict]) -> None:
    _insert_ignore(engine, vpred, rows)


def settle_markets(engine: Engine, outcomes: list[tuple[str, int]]) -> None:
    if not outcomes:
        return
    from sqlalchemy import bindparam
    stmt = (update(vmarket).where(vmarket.c.market_uid == bindparam("uid"))
            .values(settled=1, outcome=bindparam("result")))
    with engine.begin() as c:
        c.execute(stmt, [{"uid": u, "result": o} for u, o in outcomes])


def record_run(engine: Engine, run: dict) -> None:
    with engine.begin() as c:
        c.execute(ingest_run.insert(), [run])


def publish(engine: Engine, doc: dict, generated_ts: float, keep: int = 48) -> None:
    """Store the dashboard document and prune all but the newest `keep`."""
    with engine.begin() as c:
        c.execute(published_result.insert(), [{"generated_ts": generated_ts, "doc": json.dumps(doc)}])
        keep_ids = (select(published_result.c.id)
                    .order_by(published_result.c.id.desc()).limit(keep).scalar_subquery())
        c.execute(delete(published_result).where(published_result.c.id.not_in(keep_ids)))


def latest_published(engine: Engine) -> dict | None:
    with engine.connect() as c:
        row = c.execute(select(published_result.c.doc)
                        .order_by(published_result.c.id.desc()).limit(1)).first()
    return json.loads(row[0]) if row else None


def count_published(engine: Engine) -> int:
    with engine.connect() as c:
        return c.execute(select(func.count()).select_from(published_result)).scalar_one()


def _read(engine: Engine, table: Table, *where) -> list[dict]:
    with engine.connect() as c:
        return [dict(r) for r in c.execute(select(table).where(*where)).mappings()]


def read_markets(engine: Engine, *where) -> list[dict]:
    return _read(engine, vmarket, *where)


def read_quotes(engine: Engine, *where) -> list[dict]:
    return _read(engine, vquote, *where)


def read_preds(engine: Engine, *where) -> list[dict]:
    return _read(engine, vpred, *where)


def read_runs(engine: Engine) -> list[dict]:
    return _read(engine, ingest_run)
