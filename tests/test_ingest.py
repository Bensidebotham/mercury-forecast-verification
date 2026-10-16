from weather_vs_market.config import load_settings
from weather_vs_market.pipeline import ingest
from weather_vs_market.storage import store as S


def _kalshi_raw(ticker="KXHIGHNY-26OCT10-B72.5", bid="0.4000", ask="0.4400"):
    return {"ticker": ticker, "event_ticker": "KXHIGHNY-26OCT10", "title": "NYC high",
            "yes_sub_title": "72° to 73°", "close_time": "2099-10-11T05:00:00Z",
            "yes_bid_dollars": bid, "yes_ask_dollars": ask,
            "floor_strike": 72, "cap_strike": 73, "strike_type": "between", "status": "active"}


def _settings():
    s = load_settings()
    s.venues.kalshi = s.venues.kalshi[:1]
    s.venues.polymarket = []
    return s


def _patch_sources(monkeypatch, members, markets):
    monkeypatch.setattr(ingest.kalshi, "fetch_markets", lambda series, status="open": markets)
    monkeypatch.setattr(ingest.ensemble, "get_ensemble_members", lambda *a, **k: members)
    monkeypatch.setattr(ingest.obs, "get_running_max", lambda *a, **k: None)
    monkeypatch.setattr(ingest.obs, "is_day_locked", lambda *a, **k: False)


def test_failed_ensemble_fetch_is_skipped_not_stored_as_zero(monkeypatch, tmp_path):
    engine = S.connect(str(tmp_path / "v.sqlite3"))
    _patch_sources(monkeypatch, members=[], markets=[_kalshi_raw()])
    out = ingest.run_once(_settings(), engine, now=1_000.0)
    assert S.read_preds(engine) == []
    assert out["preds"] == 0 and out["skipped_preds"] == 1
    assert len(S.read_quotes(engine)) == 1      # the market side is still recorded


def test_ingest_stores_market_quote_and_prediction(monkeypatch, tmp_path):
    engine = S.connect(str(tmp_path / "v.sqlite3"))
    _patch_sources(monkeypatch, members=[72.6] * 30, markets=[_kalshi_raw()])
    out = ingest.run_once(_settings(), engine, now=1_000.0)
    m = S.read_markets(engine)[0]
    assert (m["station"], m["event_key"]) == ("KNYC", "KXHIGHNY-26OCT10")
    q = S.read_quotes(engine)[0]
    assert (q["market_prob"], q["best_bid"], q["best_ask"], q["source"]) == (0.42, 0.40, 0.44, "live")
    p = S.read_preds(engine)[0]
    assert p["model"] == ingest.ENSEMBLE_MODEL and p["model_prob"] > 0.4
    assert out["markets"] == 1 and out["quotes"] == 1 and out["preds"] == 1
    assert S.read_runs(engine)[0]["status"] == "ok"


def test_one_sided_book_stores_no_quote(monkeypatch, tmp_path):
    engine = S.connect(str(tmp_path / "v.sqlite3"))
    _patch_sources(monkeypatch, members=[72.6] * 30, markets=[_kalshi_raw(bid=None)])
    ingest.run_once(_settings(), engine, now=1_000.0)
    assert S.read_quotes(engine) == []


def test_cycle_with_no_markets_is_marked_failed(monkeypatch, tmp_path):
    # The 2026-10 Kalshi schema change silently skipped every market; that must be loud.
    engine = S.connect(str(tmp_path / "v.sqlite3"))
    _patch_sources(monkeypatch, members=[72.6] * 30, markets=[])
    out = ingest.run_once(_settings(), engine, now=1_000.0)
    assert out["status"] == "failed"
    assert S.read_runs(engine)[0]["status"] == "failed"


def _pm_event(closed=False, prices=("0.5", "0.5"), site="klga"):
    import json
    def mkt(token, q, bid, ask):
        return {"question": q, "groupItemTitle": "", "clobTokenIds": json.dumps([token, "no"]),
                "bestBid": bid, "bestAsk": ask, "closed": closed,
                "outcomePrices": json.dumps(list(prices)), "endDate": "2099-10-17T12:00:00Z"}
    return {"slug": "highest-temperature-in-nyc-on-october-17-2099",
            "title": "Highest temperature in NYC on October 17?", "endDate": "2099-10-17T12:00:00Z",
            "resolutionSource": f"https://www.weather.gov/wrh/timeseries?site={site}",
            "markets": [mkt("tokA", "Will the highest temperature in New York City be between 58-59°F "
                                    "on October 17?", 0.18, 0.22),
                        mkt("tokB", "Will the highest temperature in New York City be 60°F or higher "
                                    "on October 17?", None, 0.30)]}


def test_polymarket_live_ingest_uses_venue_station_and_two_sided_mid(monkeypatch, tmp_path):
    engine = S.connect(str(tmp_path / "v.sqlite3"))
    s = _settings()
    s.venues.kalshi = []
    s.venues.polymarket = load_settings().venues.polymarket[:1]       # NYC on KLGA
    _patch_sources(monkeypatch, members=[58.6] * 30, markets=[])
    seen = []
    monkeypatch.setattr(ingest.ph, "find_event",
                        lambda slug, d: seen.append(d) or (_pm_event() if not seen[1:] else None))
    out = ingest.run_once(s, engine, now=1_000.0)
    markets = {m["market_uid"]: m for m in S.read_markets(engine)}
    assert set(markets) == {"polymarket:tokA", "polymarket:tokB"}
    assert markets["polymarket:tokA"]["station"] == "KLGA"
    assert markets["polymarket:tokA"]["event_key"] == "highest-temperature-in-nyc-on-october-17-2099"
    assert [q["market_prob"] for q in S.read_quotes(engine)] == [0.2]    # tokB is one-sided
    assert out["preds"] == 2 and out["status"] == "ok"


def test_polymarket_event_on_unexpected_station_is_skipped(monkeypatch, tmp_path):
    engine = S.connect(str(tmp_path / "v.sqlite3"))
    s = _settings()
    s.venues.kalshi = []
    s.venues.polymarket = load_settings().venues.polymarket[:1]
    _patch_sources(monkeypatch, members=[58.6] * 30, markets=[])
    monkeypatch.setattr(ingest.ph, "find_event", lambda slug, d: _pm_event(site="kjfk"))
    out = ingest.run_once(s, engine, now=1_000.0)
    assert S.read_markets(engine) == [] and out["status"] == "failed"
