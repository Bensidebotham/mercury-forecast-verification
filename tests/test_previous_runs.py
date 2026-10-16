import copy
import json
from pathlib import Path

import httpx
import pytest

from weather_vs_market.forecast import previous_runs as pr

FIX = Path(__file__).parent / "fixtures"
NY = "America/New_York"
MODELS = ("gfs_seamless", "ecmwf_ifs025")
GFS1 = "temperature_2m_previous_day1_gfs_seamless"


def load(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(pr.time, "sleep", lambda s: None)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# fixture: GMT hours 2026-03-07T00..2026-03-09T23 at NYC; local 2026-03-08 is the 23-hour DST day

def test_parse_daily_max_groups_gmt_hours_into_local_days():
    payload = load("openmeteo_previous_runs.json")
    out = pr.parse_daily_max(payload, (1, 2), MODELS, NY)
    # local Mar 6 and Mar 9 are only partly covered by the GMT window, so dropped
    assert {k[0] for k in out} == {"2026-03-07", "2026-03-08"}
    assert len(out) == 8
    # local Mar 8 = 05Z Mar 8 .. 03Z Mar 9 (23 hours) = indices 29..51
    hourly = payload["hourly"]
    assert hourly["time"][29] == "2026-03-08T05:00"
    assert out[("2026-03-08", "gfs_seamless", 1)] == max(hourly[GFS1][29:52])
    assert out[("2026-03-07", "gfs_seamless", 2)] == 45.6


def test_parse_daily_max_without_tz_uses_payload_dates():
    out = pr.parse_daily_max(load("openmeteo_previous_runs.json"), (1,), ("gfs_seamless",))
    assert sorted(k[0] for k in out) == ["2026-03-07", "2026-03-08", "2026-03-09"]
    assert out[("2026-03-07", "gfs_seamless", 1)] == 43.0


def test_single_model_payload_has_unsuffixed_keys():
    single = load("openmeteo_previous_runs_single.json")
    assert "temperature_2m_previous_day1" in single["hourly"]
    out = pr.parse_daily_max(single, (1, 2), ("gfs_seamless",), NY)
    multi = pr.parse_daily_max(load("openmeteo_previous_runs.json"), (1, 2), MODELS, NY)
    assert out == {k: v for k, v in multi.items() if k[1] == "gfs_seamless"}


def test_unsuffixed_keys_not_attributed_when_several_models_requested():
    out = pr.parse_daily_max(load("openmeteo_previous_runs_single.json"), (1,), MODELS, NY)
    assert out == {}


def test_any_null_hour_drops_that_day_model_lead_only():
    payload = copy.deepcopy(load("openmeteo_previous_runs.json"))
    payload["hourly"][GFS1][40] = None  # inside local Mar 8
    out = pr.parse_daily_max(payload, (1, 2), MODELS, NY)
    assert ("2026-03-08", "gfs_seamless", 1) not in out
    assert ("2026-03-08", "gfs_seamless", 2) in out
    assert ("2026-03-08", "ecmwf_ifs025", 1) in out


def test_ecmwf_archive_start_is_partial_and_skipped():
    out = pr.parse_daily_max(load("openmeteo_previous_runs_ecmwf_start.json"), (1, 2), MODELS, NY)
    assert not [k for k in out if k[1] == "ecmwf_ifs025"]
    assert ("2024-02-03", "gfs_seamless", 1) in out


def test_chunks_cover_range_without_overlap():
    from datetime import date
    chunks = pr._chunks(date(2024, 1, 1), date(2025, 6, 30))
    assert chunks[0] == (date(2024, 1, 1), date(2024, 12, 31))
    assert chunks[-1] == (date(2025, 1, 1), date(2025, 6, 30))
    assert pr._chunks(date(2024, 1, 1), date(2024, 1, 1)) == [(date(2024, 1, 1), date(2024, 1, 1))]


def test_fetch_requests_gmt_padded_chunks_and_trims_to_range(monkeypatch):
    monkeypatch.setattr(pr, "CHUNK_DAYS", 1)
    payload = load("openmeteo_previous_runs.json")
    seen = []

    def handler(req):
        p = dict(req.url.params)
        seen.append((p["start_date"], p["end_date"]))
        assert p["timezone"] == "GMT" and p["temperature_unit"] == "fahrenheit"
        assert p["models"] == "gfs_seamless,ecmwf_ifs025"
        assert p["hourly"] == "temperature_2m_previous_day1,temperature_2m_previous_day2"
        assert req.headers["user-agent"].startswith("weather-vs-market/0.3")
        return httpx.Response(200, json=payload)
    out = pr.fetch_daily_max_by_lead(40.78, -73.97, NY, "2026-03-07", "2026-03-08",
                                     client=client_for(handler))
    assert seen == [("2026-03-06", "2026-03-08"), ("2026-03-07", "2026-03-09")]
    assert out == pr.parse_daily_max(payload, (1, 2), MODELS, NY)


def test_fetch_retries_5xx_and_raises_on_400():
    codes = iter([500, 429, 200])
    payload = load("openmeteo_previous_runs.json")

    def flaky(req):
        code = next(codes)
        return httpx.Response(code, json=payload if code == 200 else {"error": True})
    out = pr.fetch_daily_max_by_lead(40.78, -73.97, NY, "2026-03-08", "2026-03-08", client=client_for(flaky))
    assert set(k[0] for k in out) == {"2026-03-08"}

    calls = []

    def bad(req):
        calls.append(1)
        return httpx.Response(400, json={"reason": "Bad Request", "error": True})
    with pytest.raises(httpx.HTTPStatusError):
        pr.fetch_daily_max_by_lead(40.78, -73.97, NY, "2026-03-08", "2026-03-08", client=client_for(bad))
    assert len(calls) == 1
