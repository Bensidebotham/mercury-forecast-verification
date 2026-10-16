import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from weather_vs_market.clients import polymarket_history as ph

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(ph.time, "sleep", lambda s: None)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- slugs --------------------------------------------------------------------

def test_event_slug_uses_year_suffix_from_feb_3_2026():
    assert ph.event_slug("nyc", date(2026, 2, 24)) == "highest-temperature-in-nyc-on-february-24-2026"
    assert (ph.event_slug("los-angeles", date(2026, 10, 14))
            == "highest-temperature-in-los-angeles-on-october-14-2026")
    assert ph.event_slug("chicago", date(2026, 2, 2)) == "highest-temperature-in-chicago-on-february-2"
    assert ph.event_slug("nyc", date(2025, 3, 1)) == "highest-temperature-in-nyc-on-march-1"


def test_candidate_slugs_cover_short_month_variants():
    slugs = ph.candidate_slugs("nyc", date(2025, 1, 23))
    assert slugs[0] == "highest-temperature-in-nyc-on-january-23"
    assert "highest-temperature-in-nyc-on-jan-23" in slugs
    assert "highest-temperature-in-nyc-on-jan-23-25" in slugs
    assert len(slugs) == len(set(slugs))


def test_find_event_skips_slug_that_resolves_to_another_year():
    ev_2025 = load("polymarket_event_2025.json")[0]  # "march-1" -> 2025-03-01
    asked = []

    def handler(req):
        asked.append(req.url.params["slug"])
        if req.url.params["slug"] == "highest-temperature-in-nyc-on-march-1":
            return httpx.Response(200, json=[ev_2025])
        return httpx.Response(200, json=[])
    assert ph.find_event("nyc", date(2024, 3, 1), client=client_for(handler)) is None
    assert ph.find_event("nyc", date(2025, 3, 1), client=client_for(handler))["slug"] == ev_2025["slug"]
    assert "highest-temperature-in-nyc-on-mar-1" in asked


def test_fetch_event_none_when_slug_unknown():
    assert ph.fetch_event("nope", client=client_for(lambda r: httpx.Response(200, json=[]))) is None


# --- event parsing ----------------------------------------------------------------

def test_event_date_from_title_and_year():
    assert ph.event_date(load("polymarket_event_2026.json")[0]) == date(2026, 10, 14)
    assert ph.event_date(load("polymarket_event_2025.json")[0]) == date(2025, 3, 1)


def test_event_date_trusts_title_over_end_date_and_short_months():
    # real cases: "May 12" event ending May 13; "may-8-625" slug for May 9 with no endDate
    assert ph.event_date({"title": "Highest temperature in NYC on May 12?",
                          "endDate": "2025-05-13T12:00:00Z"}) == date(2025, 5, 12)
    assert ph.event_date({"title": "Highest temperature in NYC on May 9?", "endDate": None,
                          "startDate": "2025-05-07T16:12:35Z"}) == date(2025, 5, 9)
    assert ph.event_date({"title": "Highest temperature in NYC on Jan 22?",
                          "endDate": "2025-01-22T12:00:00Z"}) == date(2025, 1, 22)
    # listed in late December for 1 January
    assert ph.event_date({"title": "Highest temperature in NYC on January 1?",
                          "startDate": "2025-12-30T10:00:00Z"}) == date(2026, 1, 1)
    assert ph.event_date({"title": "Will it rain?"}) is None


@pytest.mark.parametrize("fixture,station", [
    ("polymarket_event_2026.json", "KLGA"),             # weather.gov ?site=klga
    ("polymarket_event_wunderground.json", "KORD"),      # wunderground .../KORD
    ("polymarket_event_2025.json", "KLGA"),             # empty source, URL in description
])
def test_resolution_station(fixture, station):
    assert ph.resolution_station(load(fixture)[0]) == station


def test_resolution_station_from_short_wunderground_url_in_description():
    ev = {"resolutionSource": "", "description": "available here: https://www.wunderground.com/weather/KORD."}
    assert ph.resolution_station(ev) == "KORD"
    assert ph.resolution_station({"resolutionSource": None, "description": "no link"}) is None


def test_resolved_outcome_thresholds():
    assert ph.resolved_outcome(["1", "0"], closed=True) == 1
    assert ph.resolved_outcome(["0.995", "0.005"], closed=True) == 1
    assert ph.resolved_outcome(["0", "1"], closed=True) == 0
    assert ph.resolved_outcome(["0.5", "0.5"], closed=True) is None
    assert ph.resolved_outcome(["1", "0"], closed=False) is None
    assert ph.resolved_outcome([], closed=True) is None


def test_parse_event_rows():
    ev = load("polymarket_event_2026.json")[0]
    rows = ph.parse_event(ev)
    assert len(rows) == len(ev["markets"])
    first = rows[0]
    assert first["token_id"] == json.loads(ev["markets"][0]["clobTokenIds"])[0]
    assert first["bucket"] == "67°F or below"
    assert first["question"].startswith("Will the highest temperature in New York City be 67°F")
    assert first["closed"] is True and first["outcome"] == 0
    assert first["station"] == "KLGA" and first["target_date"] == "2026-10-14"
    assert first["end_ts"] == datetime(2026, 10, 14, 12, tzinfo=UTC).timestamp()


def test_parse_event_yes_winner_and_missing_end_date():
    ev = load("polymarket_event_2025.json")[0]
    ev["markets"][1]["outcomePrices"] = '["1", "0"]'
    ev["endDate"] = None
    for m in ev["markets"]:
        m["endDate"] = None
    rows = ph.parse_event(ev)
    assert [r["outcome"] for r in rows] == [0, 1, 0]
    assert all(r["end_ts"] is None for r in rows)


def test_dedupe_by_date_keeps_earliest_listed():
    real = {"slug": "arch-x", "title": "Highest temperature in NYC on May 19?",
            "eventDate": "2026-05-19", "startDate": "2026-05-17T04:09:31Z"}
    relist = {"slug": "x", "title": "Highest temperature in NYC on May 19?",
              "eventDate": "2026-05-19", "startDate": "2026-05-19T22:14:24Z"}
    out = ph.dedupe_by_date([relist, real])
    assert out == {date(2026, 5, 19): real}


# --- series pagination -------------------------------------------------------------

def test_fetch_series_events_paginates_by_offset():
    events = [{"slug": f"e{i}"} for i in range(230)]
    offsets = []

    def handler(req):
        p = req.url.params
        assert p["series_slug"] == "nyc-daily-weather" and p["limit"] == "100"
        off = int(p["offset"])
        offsets.append(off)
        return httpx.Response(200, json=events[off:off + 100])
    out = ph.fetch_series_events("nyc-daily-weather", client=client_for(handler))
    assert out == events
    assert offsets == [0, 100, 200, 230]


# --- price history -----------------------------------------------------------------

def test_parse_price_history_fixture():
    pts = ph.parse_price_history(load("clob_prices_history.json"))
    assert pts[0] == (1791795624, 0.065)
    assert all(isinstance(t, int) and 0 <= p <= 1 for t, p in pts)
    assert ph.parse_price_history({}) == []


def test_fetch_price_history_sends_explicit_window_and_chunks():
    windows = []

    def handler(req):
        p = req.url.params
        assert "interval" not in p and p["fidelity"] == "60" and p["market"] == "tok"
        lo, hi = int(p["startTs"]), int(p["endTs"])
        assert hi - lo <= ph.MAX_WINDOW_S
        windows.append((lo, hi))
        return httpx.Response(200, json={"history": [{"t": lo, "p": 0.2}, {"t": hi, "p": 0.3}]})
    day = 86400
    pts = ph.fetch_price_history("tok", 0, 40 * day, client=client_for(handler))
    assert windows == [(0, 15 * day), (15 * day, 30 * day), (30 * day, 40 * day)]
    assert [t for t, _ in pts] == [0, 15 * day, 30 * day, 40 * day]


def test_price_history_retries_429_but_not_400():
    codes = iter([429, 200])

    def flaky(req):
        code = next(codes)
        return httpx.Response(code, json=load("clob_prices_history.json") if code == 200 else {})
    assert len(ph.fetch_price_history("tok", 0, 3600, client=client_for(flaky))) == 6

    calls = []

    def bad(req):
        calls.append(1)
        return httpx.Response(400, json={"error": "interval is too long"})
    with pytest.raises(httpx.HTTPStatusError):
        ph.fetch_price_history("tok", 0, 3600, client=client_for(bad))
    assert len(calls) == 1
