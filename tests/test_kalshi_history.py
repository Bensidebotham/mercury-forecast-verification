import json
from pathlib import Path

import httpx
import pytest

from weather_vs_market.clients import kalshi_history as kh

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(kh.time, "sleep", lambda s: None)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- parse_candles ------------------------------------------------------------

def test_parse_candles_live_schema_reads_close_dollars():
    rows = kh.parse_candles(load("kalshi_candles_live.json"))
    assert rows[0] == {"ts": 1791990000, "yes_bid": 0.01, "yes_ask": 0.02}
    assert len(rows) == 5


def test_parse_candles_historical_schema_reads_close():
    rows = kh.parse_candles(load("kalshi_candles_historical.json"))
    assert rows[0] == {"ts": 1786719600, "yes_bid": 0.03, "yes_ask": 0.07}
    assert rows[1] == {"ts": 1786723200, "yes_bid": 0.03, "yes_ask": 0.04}


def test_parse_candles_prices_in_unit_interval_and_sorted():
    for name in ("kalshi_candles_live.json", "kalshi_candles_historical.json"):
        rows = kh.parse_candles(load(name))
        assert [r["ts"] for r in rows] == sorted(r["ts"] for r in rows)
        for r in rows:
            for side in ("yes_bid", "yes_ask"):
                assert r[side] is None or 0.0 <= r[side] <= 1.0


def test_parse_candles_missing_or_null_sides_are_none():
    payload = {"candlesticks": [
        {"end_period_ts": 20, "yes_bid": {"close": None}, "yes_ask": {}},
        {"end_period_ts": 10, "yes_bid": {"close_dollars": "0.5000"}},
    ]}
    assert kh.parse_candles(payload) == [
        {"ts": 10, "yes_bid": 0.5, "yes_ask": None},
        {"ts": 20, "yes_bid": None, "yes_ask": None},
    ]


def test_parse_candles_empty_payload():
    assert kh.parse_candles({"candlesticks": None}) == []


# --- historical vs live ---------------------------------------------------------

def test_is_historical_splits_on_settlement_vs_cutoff():
    cutoff = kh._ts(load("kalshi_cutoff.json")["market_settled_ts"])
    hist = load("kalshi_historical_markets.json")["markets"][0]
    live = load("kalshi_live_markets.json")["markets"][0]
    assert kh.is_historical(hist, cutoff) is True
    assert kh.is_historical(live, cutoff) is False


def test_is_historical_falls_back_to_close_time():
    cutoff = kh._ts("2026-08-17T00:00:00Z")
    assert kh.is_historical({"close_time": "2026-08-01T04:59:00Z"}, cutoff)
    assert not kh.is_historical({"close_time": "2026-09-01T04:59:00Z"}, cutoff)


def test_fetch_cutoff_returns_epoch():
    def handler(req):
        assert req.url.path.endswith("/historical/cutoff")
        return httpx.Response(200, json=load("kalshi_cutoff.json"))
    assert kh.fetch_cutoff(client=client_for(handler)) == kh._ts("2026-08-17T00:00:00Z")


# --- fetch_settled_markets ------------------------------------------------------

def test_fetch_settled_markets_paginates_both_sources_and_dedupes():
    hist = load("kalshi_historical_markets.json")["markets"]
    live = load("kalshi_live_markets.json")["markets"]
    overlap = dict(hist[1], custom_strike=None)  # same ticker listed in both
    seen = []

    def handler(req):
        p = dict(req.url.params)
        seen.append((req.url.path, p))
        assert req.headers["user-agent"].startswith("weather-vs-market/0.3")
        assert p["series_ticker"] == "KXHIGHMIA" and p["limit"] == "1000"
        if req.url.path.endswith("/historical/markets"):
            if "cursor" not in p:
                return httpx.Response(200, json={"cursor": "page2", "markets": [hist[0]]})
            return httpx.Response(200, json={"cursor": "", "markets": [hist[1]]})
        assert p["status"] == "settled"
        if "cursor" not in p:
            return httpx.Response(200, json={"cursor": "next", "markets": live + [overlap]})
        return httpx.Response(200, json={"cursor": "more", "markets": []})

    out = kh.fetch_settled_markets("KXHIGHMIA", client=client_for(handler))
    tickers = [m["ticker"] for m in out]
    assert len(tickers) == len(set(tickers)) == 4
    assert tickers[:2] == sorted(m["ticker"] for m in hist)  # oldest close first
    assert "custom_strike" in next(m for m in out if m["ticker"] == hist[1]["ticker"])
    assert len(seen) == 4


# --- retries ---------------------------------------------------------------------

def test_retries_429_and_5xx_then_succeeds():
    codes = iter([429, 502, 200])
    calls = []

    def handler(req):
        calls.append(1)
        code = next(codes)
        return httpx.Response(code, json=load("kalshi_cutoff.json") if code == 200 else {})
    assert kh.fetch_cutoff(client=client_for(handler)) > 0
    assert len(calls) == 3


def test_gives_up_after_max_tries():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503)
    with pytest.raises(httpx.HTTPStatusError):
        kh.fetch_cutoff(client=client_for(handler))
    assert len(calls) == kh.MAX_TRIES


def test_does_not_retry_404():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(404, json={"error": {"code": "not_found"}})
    with pytest.raises(httpx.HTTPStatusError):
        kh.fetch_hourly_quotes("KXHIGHMIA", "X", 0, 3600, historical=False, client=client_for(handler))
    assert len(calls) == 1


# --- fetch_hourly_quotes -------------------------------------------------------

TICKER = "KXHIGHMIA-26AUG15-T95"


@pytest.mark.parametrize("historical,path,fixture", [
    (True, f"/trade-api/v2/historical/markets/{TICKER}/candlesticks", "kalshi_candles_historical.json"),
    (False, f"/trade-api/v2/series/KXHIGHMIA/markets/{TICKER}/candlesticks", "kalshi_candles_live.json"),
])
def test_fetch_hourly_quotes_routes_by_flag(historical, path, fixture):
    def handler(req):
        assert req.url.path == path
        assert req.url.params["period_interval"] == "60"
        return httpx.Response(200, json=load(fixture))
    rows = kh.fetch_hourly_quotes("KXHIGHMIA", "KXHIGHMIA-26AUG15-T95", 1786716000, 1786842000,
                                  historical=historical, client=client_for(handler))
    assert rows == kh.parse_candles(load(fixture))


def test_fetch_hourly_quotes_chunks_at_5000_candles_and_merges():
    windows = []

    def handler(req):
        lo, hi = int(req.url.params["start_ts"]), int(req.url.params["end_ts"])
        windows.append((lo, hi))
        assert (hi - lo) // 3600 <= kh.MAX_CANDLES
        # candles at both window edges, so the shared boundary is returned twice
        cs = [{"end_period_ts": t, "yes_bid": {"close": "0.1"}, "yes_ask": {"close": "0.2"}}
              for t in (lo, hi)]
        return httpx.Response(200, json={"candlesticks": cs})
    start, end = 0, 6000 * 3600
    rows = kh.fetch_hourly_quotes("S", "T", start, end, historical=True, client=client_for(handler))
    assert windows == [(0, 5000 * 3600), (5000 * 3600, 6000 * 3600)]
    assert [r["ts"] for r in rows] == [0, 5000 * 3600, 6000 * 3600]
