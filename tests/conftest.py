"""Shared fixtures.

`store` runs each storage test against SQLite, and also against Postgres when
WVM_TEST_DATABASE_URL is set (CI service container, or a Neon dev branch
locally). Each Postgres test gets its own throwaway schema.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from weather_vs_market.storage import store as S

PG_URL = os.environ.get("WVM_TEST_DATABASE_URL")
BACKENDS = ["sqlite"] + (["postgres"] if PG_URL else [])


@pytest.fixture(params=BACKENDS)
def engine(request, tmp_path):
    if request.param == "sqlite":
        eng = S.connect(str(tmp_path / "v.sqlite3"))
        yield eng
        eng.dispose()
        return
    schema = f"t_{uuid.uuid4().hex[:12]}"
    admin = create_engine(S.normalize_url(PG_URL))
    with admin.begin() as c:
        c.execute(text(f"CREATE SCHEMA {schema}"))
    eng = S.connect(PG_URL, schema=schema)
    yield eng
    eng.dispose()
    with admin.begin() as c:
        c.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    admin.dispose()


def market(uid="kalshi:T1", **kw):
    row = {
        "market_uid": uid, "venue": uid.split(":")[0], "external_id": uid.split(":")[1],
        "event_key": "EV1", "city": "New York", "station": "KNYC", "target_date": "2026-06-22",
        "bucket_lo": 75.0, "bucket_hi": 76.0, "unit": "F", "question": "q", "close_ts": 1_000_000.0,
    }
    row.update(kw)
    return row
