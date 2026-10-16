from weather_vs_market.pipeline.settle import kalshi_outcomes, outcome_from_result


def test_outcome_from_result():
    assert outcome_from_result("yes") == 1
    assert outcome_from_result("no") == 0
    assert outcome_from_result(None) is None
    assert outcome_from_result("") is None


def test_kalshi_outcomes_only_for_known_markets_with_results():
    raw = [{"ticker": "A", "result": "yes"}, {"ticker": "B", "result": "no"},
           {"ticker": "C", "result": "yes"}, {"ticker": "D", "result": ""}]
    assert kalshi_outcomes(raw, {"kalshi:A", "kalshi:B", "kalshi:D"}) == [
        ("kalshi:A", 1), ("kalshi:B", 0)]


def test_settle_polymarket_from_closed_event(monkeypatch, tmp_path):
    from test_ingest import _pm_event

    from conftest import market
    from weather_vs_market.config import load_settings
    from weather_vs_market.pipeline import settle
    from weather_vs_market.storage import store as S

    engine = S.connect(str(tmp_path / "v.sqlite3"))
    slug = "highest-temperature-in-nyc-on-october-17-2099"
    S.upsert_markets(engine, [market("polymarket:tokA", event_key=slug, close_ts=10.0),
                              market("polymarket:tokB", event_key=slug, close_ts=10.0)])
    closed = _pm_event(closed=True, prices=("0", "1"))
    closed["markets"][0]["outcomePrices"] = '["1", "0"]'          # tokA won
    monkeypatch.setattr(settle.ph, "fetch_event", lambda s: closed)
    assert settle.settle_polymarket(load_settings(), engine, now=100.0) == 2
    outcomes = {m["market_uid"]: m["outcome"] for m in S.read_markets(engine)}
    assert outcomes == {"polymarket:tokA": 1, "polymarket:tokB": 0}
