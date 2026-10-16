import time

from conftest import market
from weather_vs_market.analysis import live
from weather_vs_market.storage import store as S

NOW = 1_800_000_000.0


def _seed(engine, uid, model_p, market_p, close_ts, settled=False):
    S.upsert_markets(engine, [market(uid, close_ts=close_ts)])
    S.insert_quotes(engine, [{"ts": NOW - 60, "market_uid": uid, "market_prob": market_p,
                              "best_bid": None, "best_ask": None, "source": "live"}])
    S.insert_preds(engine, [{"ts": NOW - 60, "market_uid": uid, "model": "m1",
                             "model_prob": model_p, "lead_hours": 24.0}])
    if settled:
        S.settle_markets(engine, [(uid, 1)])


def test_disagreements_rank_by_abs_gap_and_exclude_settled(engine):
    future = NOW + 24 * 3600
    _seed(engine, "kalshi:A", 0.80, 0.50, future)
    _seed(engine, "kalshi:B", 0.40, 0.45, future)
    _seed(engine, "kalshi:C", 0.90, 0.10, future, settled=True)
    rows = live.current_disagreements(engine, model="m1", now=NOW)
    assert [r["market_uid"] for r in rows] == ["kalshi:A", "kalshi:B"]
    assert rows[0]["gap"] == 0.30 and rows[0]["lead_hours"] == 24.0


def test_disagreements_skip_markets_missing_a_side_or_past_close(engine):
    S.upsert_markets(engine, [market("kalshi:D", close_ts=NOW + 3600 * 24)])
    S.insert_preds(engine, [{"ts": NOW, "market_uid": "kalshi:D", "model": "m1",
                             "model_prob": 0.7, "lead_hours": 24.0}])
    _seed(engine, "kalshi:PAST", 0.0, 0.99, NOW - 3600)
    assert live.current_disagreements(engine, model="m1", now=NOW) == []


def test_disagreements_ignore_other_models_and_backtest_quotes(engine):
    _seed(engine, "kalshi:A", 0.80, 0.50, NOW + 24 * 3600)
    S.insert_quotes(engine, [{"ts": NOW, "market_uid": "kalshi:A", "market_prob": 0.9,
                              "best_bid": None, "best_ask": None, "source": "kalshi_candles"}])
    assert live.current_disagreements(engine, model="other", now=NOW) == []
    assert live.current_disagreements(engine, model="m1", now=NOW)[0]["market_prob"] == 0.50


def test_tracking_summary_counts(engine):
    _seed(engine, "kalshi:A", 0.8, 0.5, NOW + 24 * 3600)
    _seed(engine, "kalshi:C", 0.9, 0.1, NOW + 24 * 3600, settled=True)
    S.record_run(engine, {"run_id": "r", "started_ts": time.time(), "status": "ok"})
    s = live.tracking_summary(engine)
    assert (s["n_markets"], s["n_open"], s["n_settled"]) == (2, 1, 1)
    assert s["n_live_quotes"] == 2 and s["n_preds"] == 2
    assert s["last_run"]["status"] == "ok"
