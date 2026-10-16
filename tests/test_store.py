import pytest

from conftest import market
from weather_vs_market.storage import store as S


def test_round_trip_market_quote_pred_and_settlement(engine):
    S.upsert_markets(engine, [market()])
    S.insert_quotes(engine, [{"ts": 10.0, "market_uid": "kalshi:T1", "market_prob": 0.42,
                              "best_bid": 0.40, "best_ask": 0.44, "source": "live"}])
    S.insert_preds(engine, [{"ts": 10.0, "market_uid": "kalshi:T1", "model": "m1",
                             "model_prob": 0.55, "lead_hours": 48.0}])
    S.settle_markets(engine, [("kalshi:T1", 1)])

    m = S.read_markets(engine)[0]
    assert m["settled"] == 1 and m["outcome"] == 1 and m["station"] == "KNYC"
    assert S.read_quotes(engine)[0]["market_prob"] == 0.42
    assert S.read_preds(engine)[0]["model_prob"] == 0.55


def test_upsert_updates_metadata_but_keeps_settlement(engine):
    S.upsert_markets(engine, [market()])
    S.settle_markets(engine, [("kalshi:T1", 0)])
    S.upsert_markets(engine, [market(question="new q", close_ts=2_000_000.0)])
    m = S.read_markets(engine)[0]
    assert m["question"] == "new q" and m["close_ts"] == 2_000_000.0
    assert m["settled"] == 1 and m["outcome"] == 0


def test_snapshot_inserts_are_idempotent(engine):
    S.upsert_markets(engine, [market()])
    q = {"ts": 10.0, "market_uid": "kalshi:T1", "market_prob": 0.4, "best_bid": None,
         "best_ask": None, "source": "live"}
    p = {"ts": 10.0, "market_uid": "kalshi:T1", "model": "m1", "model_prob": 0.5, "lead_hours": 1.0}
    for _ in range(2):
        S.insert_quotes(engine, [q])
        S.insert_preds(engine, [p])
    assert len(S.read_quotes(engine)) == 1
    assert len(S.read_preds(engine)) == 1
    # a different model at the same timestamp is a separate prediction
    S.insert_preds(engine, [{**p, "model": "m2"}])
    assert len(S.read_preds(engine)) == 2


def test_empty_batches_are_no_ops(engine):
    S.upsert_markets(engine, [])
    S.insert_quotes(engine, [])
    S.insert_preds(engine, [])
    S.settle_markets(engine, [])
    assert S.read_markets(engine) == []


def test_publish_keeps_only_latest_docs(engine):
    assert S.latest_published(engine) is None
    for i in range(5):
        S.publish(engine, {"i": i}, generated_ts=float(i), keep=3)
    assert S.latest_published(engine) == {"i": 4}
    assert S.count_published(engine) == 3


def test_record_run(engine):
    S.record_run(engine, {"run_id": "r1", "started_ts": 1.0, "finished_ts": 2.0, "status": "ok",
                          "n_markets": 3, "n_quotes": 3, "n_preds": 2, "n_skipped": 1,
                          "detail": "{}"})
    assert S.read_runs(engine)[0]["n_skipped"] == 1


@pytest.mark.parametrize("url,expected", [
    ("postgresql://u:p@h/db?sslmode=require", "postgresql+psycopg://u:p@h/db?sslmode=require"),
    ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("data/verify.sqlite3", "sqlite:///data/verify.sqlite3"),
    ("sqlite:///x.db", "sqlite:///x.db"),
])
def test_normalize_url(url, expected):
    assert S.normalize_url(url) == expected
