import math

import pytest

from conftest import market
from weather_vs_market.analysis import verification as V
from weather_vs_market.storage import store as S

LEAD = V.LeadPoint("D-1 12:00", day_offset=-1, hour=12)
# 2026-06-21 12:00 America/New_York = 16:00 UTC
POINT_TS = 1782057600.0


def test_lead_point_timestamp_is_local_clock_time():
    assert LEAD.timestamp("2026-06-22", "America/New_York") == POINT_TS


def _event(engine, *, probs_model, probs_market, winner, event="EV1", city="New York",
           date="2026-06-22", quote_ts=POINT_TS - 600, pred_ts=POINT_TS - 600, model="m1"):
    """Seed a 3-bucket ladder (<=74, 75-76, >=77) for one city-day."""
    ladder = [(None, 74.0), (75.0, 76.0), (77.0, None)]
    rows, quotes, preds, outcomes = [], [], [], []
    for i, (lo, hi) in enumerate(ladder):
        uid = f"kalshi:{event}-{i}"
        rows.append(market(uid, event_key=event, city=city, target_date=date,
                           bucket_lo=lo, bucket_hi=hi))
        quotes.append({"ts": quote_ts, "market_uid": uid, "market_prob": probs_market[i],
                       "best_bid": None, "best_ask": None, "source": "live"})
        preds.append({"ts": pred_ts, "market_uid": uid, "model": model,
                      "model_prob": probs_model[i], "lead_hours": 0.0})
        outcomes.append((uid, int(i == winner)))
    S.upsert_markets(engine, rows)
    S.insert_quotes(engine, quotes)
    S.insert_preds(engine, preds)
    S.settle_markets(engine, outcomes)


def test_event_scores_normalize_market_ladder(engine):
    # market mids sum to 1.2 (overround); they are normalized before scoring
    _event(engine, probs_model=[0.1, 0.8, 0.1], probs_market=[0.24, 0.72, 0.24], winner=1)
    frame = V.event_frame(engine, venue="kalshi", model="m1", lead_points=[LEAD],
                          tz_for_city={"New York": "America/New_York"})
    assert len(frame) == 1
    ev = frame[0]
    assert ev["market_probs"] == pytest.approx([0.2, 0.6, 0.2])
    # multi-category Brier: sum over buckets of (p - o)^2
    assert ev["model_brier"] == pytest.approx(0.01 + 0.04 + 0.01)
    assert ev["market_brier"] == pytest.approx(0.04 + 0.16 + 0.04)
    assert ev["model_logscore"] == pytest.approx(-math.log(0.8))


def test_snapshots_after_the_lead_point_are_never_used(engine):
    # A quote taken after the lead time would leak information. No as-of data -> no row.
    _event(engine, probs_model=[0.1, 0.8, 0.1], probs_market=[0.2, 0.6, 0.2], winner=1,
           quote_ts=POINT_TS + 60)
    assert V.event_frame(engine, venue="kalshi", model="m1", lead_points=[LEAD],
                         tz_for_city={"New York": "America/New_York"}) == []


def test_stale_snapshots_beyond_tolerance_are_dropped(engine):
    _event(engine, probs_model=[0.1, 0.8, 0.1], probs_market=[0.2, 0.6, 0.2], winner=1,
           pred_ts=POINT_TS - 3 * 3600)
    assert V.event_frame(engine, venue="kalshi", model="m1", lead_points=[LEAD],
                         tz_for_city={"New York": "America/New_York"}, tolerance_s=2 * 3600) == []


def test_incomplete_ladder_is_not_scored(engine):
    _event(engine, probs_model=[0.1, 0.8, 0.1], probs_market=[0.2, 0.6, 0.2], winner=1)
    # drop one bucket's quote by settling a fourth, unquoted bucket into the same event
    S.upsert_markets(engine, [market("kalshi:EV1-3", event_key="EV1", bucket_lo=78.0,
                                     bucket_hi=79.0)])
    S.settle_markets(engine, [("kalshi:EV1-3", 0)])
    assert V.event_frame(engine, venue="kalshi", model="m1", lead_points=[LEAD],
                         tz_for_city={"New York": "America/New_York"}) == []


def test_probability_floor_bounds_log_score(engine):
    _event(engine, probs_model=[0.0, 0.0, 1.0], probs_market=[0.2, 0.6, 0.2], winner=1)
    ev = V.event_frame(engine, venue="kalshi", model="m1", lead_points=[LEAD],
                       tz_for_city={"New York": "America/New_York"})[0]
    assert ev["model_logscore"] == pytest.approx(-math.log(V.PROB_FLOOR))


def test_rps_rewards_near_misses():
    # winner is bucket 1; putting mass on the adjacent bucket beats the far one
    near = V.rps([0.0, 0.0, 1.0, 0.0], winner=1)
    far = V.rps([0.0, 0.0, 0.0, 1.0], winner=1)
    assert near < far
    assert V.rps([0.0, 1.0, 0.0, 0.0], winner=1) == 0.0


def test_summary_bootstraps_paired_difference_by_event():
    events = [{"lead": "L", "model_brier": 0.2, "market_brier": 0.3, "model_rps": 0.1,
               "market_rps": 0.15, "model_logscore": 1.0, "market_logscore": 1.2}
              for _ in range(50)]
    s = V.summarize(events, n_boot=200, seed=1)[0]
    assert s["n_events"] == 50
    assert s["brier_diff"] == pytest.approx(-0.1)
    # identical events -> zero-width interval around the difference
    assert s["brier_diff_ci"] == pytest.approx([-0.1, -0.1])


def test_calibration_pairs_use_normalized_probs():
    events = [{"model_probs": [0.1, 0.9], "market_probs": [0.3, 0.7], "outcomes": [0, 1]}]
    model_pairs, market_pairs = V.calibration_pairs(events)
    assert model_pairs == [(0.1, 0), (0.9, 1)]
    assert market_pairs == [(0.3, 0), (0.7, 1)]


def test_brier_and_log_loss():
    assert V.brier(0.7, 1) == pytest.approx(0.09)
    assert V.log_loss(0.8, 1) == pytest.approx(-math.log(0.8))


def test_calibration_curve_buckets_and_winrate():
    curve = V.calibration_curve([(0.1, 0), (0.15, 0), (0.85, 1), (0.9, 1)], bins=2)
    assert curve[0]["n"] == 2 and curve[0]["win_rate"] == 0.0
    assert curve[-1]["n"] == 2 and curve[-1]["win_rate"] == 1.0


def test_date_window_and_drop_reasons_are_reported(engine):
    _event(engine, probs_model=[0.1, 0.8, 0.1], probs_market=[0.2, 0.6, 0.2], winner=1)
    _event(engine, probs_model=[0.1, 0.8, 0.1], probs_market=[0.2, 0.6, 0.2], winner=1,
           event="EV2", date="2026-07-22")
    _event(engine, probs_model=[0.1, 0.8, 0.1], probs_market=[0.2, 0.6, 0.2], winner=1,
           event="EV3", quote_ts=POINT_TS + 60)
    stats = {}
    frame = V.event_frame(engine, venue="kalshi", model="m1", lead_points=[LEAD],
                          tz_for_city={"New York": "America/New_York"},
                          date_range=("2026-06-01", "2026-06-30"), stats=stats)
    assert [e["event_key"] for e in frame] == ["EV1"]
    assert stats == {"events_in_window": 2, "scored": 1, "missing_market": 1}


def test_summary_rows_follow_lead_order():
    base = {"model_brier": 0.2, "market_brier": 0.3, "model_rps": 0.1, "market_rps": 0.1,
            "model_logscore": 1.0, "market_logscore": 1.0}
    events = [{**base, "lead": "B"}, {**base, "lead": "A"}]
    assert [r["lead"] for r in V.summarize(events, n_boot=10, order=["A", "B"])] == ["A", "B"]


def test_ladder_with_a_gap_is_dropped_as_incomplete(engine):
    # buckets <=74 and >=77 only: 75-76 is missing, so the ladder doesn't cover every outcome
    for i, (lo, hi, won) in enumerate([(None, 74.0, 0), (77.0, None, 1)]):
        uid = f"kalshi:GAP-{i}"
        S.upsert_markets(engine, [market(uid, event_key="GAP", bucket_lo=lo, bucket_hi=hi)])
        S.insert_quotes(engine, [{"ts": POINT_TS - 60, "market_uid": uid, "market_prob": 0.5,
                                  "best_bid": None, "best_ask": None, "source": "live"}])
        S.insert_preds(engine, [{"ts": POINT_TS - 60, "market_uid": uid, "model": "m1",
                                 "model_prob": 0.5, "lead_hours": 0.0}])
        S.settle_markets(engine, [(uid, won)])
    stats = {}
    assert V.event_frame(engine, venue="kalshi", model="m1", lead_points=[LEAD],
                         tz_for_city={"New York": "America/New_York"}, stats=stats) == []
    assert stats["incomplete_ladder"] == 1


def test_bootstrap_does_not_depend_on_row_order():
    import random
    base = {"lead": "L", "model_rps": 0.1, "market_rps": 0.1, "model_logscore": 1.0,
            "market_logscore": 1.0}
    events = [{**base, "event_key": f"E{i}", "model_brier": 0.1 * (i % 7), "market_brier": 0.3}
              for i in range(40)]
    shuffled = events[:]
    random.Random(5).shuffle(shuffled)
    assert V.summarize(events, n_boot=300) == V.summarize(shuffled, n_boot=300)
