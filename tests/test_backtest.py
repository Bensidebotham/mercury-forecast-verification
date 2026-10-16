import json

import pytest

from weather_vs_market.analysis import verification as V
from weather_vs_market.config import load_settings
from weather_vs_market.model import det_gauss as D
from weather_vs_market.pipeline import backtest as B
from weather_vs_market.storage import store as S


def test_kalshi_price_needs_two_sides_and_a_tight_spread():
    assert B.kalshi_price({"yes_bid": 0.40, "yes_ask": 0.44}) == 0.42
    assert B.kalshi_price({"yes_bid": None, "yes_ask": 0.44}) is None
    assert B.kalshi_price({"yes_bid": 0.10, "yes_ask": 0.40}) is None      # spread 0.30


def test_as_of_never_looks_past_the_lead_point():
    pts = [(100.0, 0.1), (200.0, 0.2), (301.0, 0.9)]
    assert B.as_of(pts, 300.0, tolerance_s=1000) == (200.0, 0.2)
    assert B.as_of(pts, 300.0, tolerance_s=50) is None
    assert B.as_of(pts, 50.0, tolerance_s=1000) is None


def test_polymarket_bucket_from_question_or_label():
    assert B._polymarket_bucket({"question": "Will the highest temperature in NYC be between 82-83°F "
                                             "on June 10?", "bucket": ""}) == (82.0, 83.0)
    assert B._polymarket_bucket({"question": "?", "bucket": "64 or below"}) == (None, 64.0)
    assert B._polymarket_bucket({"question": "?", "bucket": "?"}) is None


def _kalshi_raw(ticker, strike_type, floor, cap, result):
    return {"ticker": ticker, "event_ticker": "KXHIGHNY-25JUL10", "title": "NYC high",
            "close_time": "2025-07-11T03:59:00Z", "strike_type": strike_type,
            "floor_strike": floor, "cap_strike": cap, "result": result}


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    """Kalshi + Open-Meteo stubs for one NYC ladder on 2025-07-10."""
    settings = load_settings()
    settings.venues.kalshi = settings.venues.kalshi[:1]
    settings.venues.polymarket = []
    ladder = [_kalshi_raw("KXHIGHNY-25JUL10-T84", "less", None, 85, "no"),
              _kalshi_raw("KXHIGHNY-25JUL10-B85.5", "between", 85, 86, "yes"),
              _kalshi_raw("KXHIGHNY-25JUL10-T86", "greater", 86, None, "no")]
    tz = "America/New_York"
    lp_ts = [V.LeadPoint(lp.name, lp.day_offset, lp.hour).timestamp("2025-07-10", tz)
             for lp in settings.evaluation.lead_points]
    after = max(lp_ts) + 60

    def candles(series, ticker, start_ts, end_ts, historical):
        mid = {"T84": 0.2, "B85.5": 0.6, "T86": 0.2}[ticker.rsplit("-", 1)[1]]
        rows = [{"ts": t - 1800, "yes_bid": mid - 0.01, "yes_ask": mid + 0.01} for t in lp_ts]
        # a post-lead candle that must never be used
        rows.append({"ts": after, "yes_bid": 0.98, "yes_ask": 0.99})
        return rows

    monkeypatch.setattr(B.kh, "fetch_cutoff", lambda: 0.0)
    monkeypatch.setattr(B.kh, "fetch_settled_markets", lambda series: ladder)
    monkeypatch.setattr(B.kh, "fetch_hourly_quotes", candles)
    monkeypatch.setattr(B.previous_runs, "fetch_daily_max_by_lead", lambda *a, **k: {
        ("2025-07-10", m, n): 84.0 for m in D.MODELS for n in (1, 2)})
    monkeypatch.setattr(B, "load_params", lambda truth: {
        ("KNYC", 1): D.Params(1.5, 1.0, 100), ("KNYC", 2): D.Params(1.5, 1.5, 100)})
    return settings, S.connect(str(tmp_path / "v.sqlite3"))


def test_collect_forecast_score_end_to_end(stubbed, monkeypatch, tmp_path):
    settings, engine = stubbed
    assert B.collect_kalshi(settings, engine, "2025-07-01", "2025-07-31")["markets"] == 3
    # resumable: a second pass fetches nothing new
    assert B.collect_kalshi(settings, engine, "2025-07-01", "2025-07-31")["quotes"] == 0
    assert all(q["market_prob"] < 0.9 for q in S.read_quotes(engine))   # post-lead candle unused
    assert B.forecast(settings, engine, "2025-07-01", "2025-07-31")["preds"] == 6

    monkeypatch.setattr(B, "ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "det_gauss_v1.params.json").write_text(json.dumps({"params": []}))
    monkeypatch.setattr(B, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(B, "cli_agreement", lambda *a: {"n": 0})
    doc = B.score(settings, engine, ("2025-07-01", "2025-07-31"), "dev")
    summary = doc["venues"]["kalshi"]["summary"]
    assert {r["lead"] for r in summary} == {"D-1 12:00", "D 08:00"}
    assert all(r["n_events"] == 1 for r in summary)
    assert (tmp_path / "results" / "backtest_dev.json").exists()


def test_kalshi_lead_quote_uses_latest_candle_even_if_it_has_no_price():
    candles = [{"ts": 100.0, "yes_bid": 0.40, "yes_ask": 0.44},
               {"ts": 200.0, "yes_bid": 0.10, "yes_ask": 0.60}]          # latest is too wide
    assert B.kalshi_lead_quote("kalshi:A", candles, 300.0, 1000, "kalshi_candles") is None
    q = B.kalshi_lead_quote("kalshi:A", candles[:1], 300.0, 1000, "kalshi_candles")
    assert (q["ts"], q["market_prob"], q["best_bid"], q["best_ask"]) == (100.0, 0.42, 0.40, 0.44)


def test_polymarket_points_count_only_from_the_end_of_their_hour():
    history = [(1000.0, 0.3), (4600.0, 0.7)]
    # at 5000 the 4600 point (usable from 8200) is not yet safe; the 1000 point (usable from 4600) is
    q = B.polymarket_lead_quote("polymarket:A", history, 5000.0, 10_000, "polymarket_history")
    assert (q["ts"], q["market_prob"]) == (4600.0, 0.3)


def test_forecast_uses_metar_truth_params_for_polymarket(monkeypatch, tmp_path):
    from conftest import market
    settings = load_settings()
    engine = S.connect(str(tmp_path / "v.sqlite3"))
    S.upsert_markets(engine, [market("polymarket:T", venue="polymarket", event_key="EVP",
                                     station="KLGA", target_date="2025-07-10", bucket_lo=None,
                                     bucket_hi=None, close_ts=2e9)])
    monkeypatch.setattr(B.previous_runs, "fetch_daily_max_by_lead", lambda *a, **k: {
        ("2025-07-10", m, n): 84.0 for m in D.MODELS for n in (1, 2)})
    used = []
    monkeypatch.setattr(B, "load_params", lambda truth: used.append(truth) or {
        ("KLGA", 1): D.Params(0, 1, 100), ("KLGA", 2): D.Params(0, 1, 100)})
    B.forecast(settings, engine, "2025-07-01", "2025-07-31")
    assert set(used) == {"metar"}


def test_polymarket_bucket_survives_question_typos():
    # Real 2025-05-04 NYC question: "be tween" instead of "between"
    row = {"question": "Will the highest temperature in NYC be be tween 70-71°F on May 4?",
           "bucket": "70-71°F"}
    assert B._polymarket_bucket(row) == (70.0, 71.0)
