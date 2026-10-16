import json
from pathlib import Path

import httpx
import pytest

from weather_vs_market import http
from weather_vs_market.forecast import iem

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- CLI ----------------------------------------------------------------------

def test_parse_cli_highs_skips_missing():
    out = iem.parse_cli_highs(load("iem_cli.json"))
    assert out["2026-01-01"] == 68 and out["2026-01-02"] == 72
    assert "2026-04-11" not in out  # high == "M"
    assert all(isinstance(v, int) for v in out.values())


def test_parse_cli_highs_with_tz_drops_preliminary_report():
    payload = load("iem_cli.json")
    # 2026-10-16 comes from a CLI issued 20:33Z that afternoon; 10-15's was issued 06:16Z next day
    assert "2026-10-16" in iem.parse_cli_highs(payload)
    final = iem.parse_cli_highs(payload, tz="America/New_York")
    assert "2026-10-16" not in final
    assert final["2026-10-15"] == 64


def test_parse_cli_highs_null_and_empty():
    assert iem.parse_cli_highs({"results": [{"valid": "2026-01-01", "high": None}]}) == {}
    assert iem.parse_cli_highs({"results": []}) == {}


def test_fetch_cli_highs_params_and_retry():
    codes = iter([503, 200])

    def handler(req):
        assert req.url.path == "/json/cli.py"
        assert dict(req.url.params) == {"station": "KMIA", "year": "2026"}
        assert req.headers["user-agent"].startswith("weather-vs-market/0.3")
        code = next(codes)
        return httpx.Response(code, json=load("iem_cli.json") if code == 200 else {})
    out = iem.fetch_cli_highs("KMIA", 2026, client=client_for(handler))
    assert out["2026-01-01"] == 68


def test_fetch_cli_highs_no_retry_on_422():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(422, json={"detail": "bad station"})
    with pytest.raises(httpx.HTTPStatusError):
        iem.fetch_cli_highs("MIA", 2026, client=client_for(handler))
    assert len(calls) == 1


# --- ASOS -----------------------------------------------------------------------

def test_parse_asos_csv_fixture():
    rows = iem.parse_asos_csv((FIX / "iem_asos.csv").read_text())
    assert rows[0] == ("2026-10-14T00:53", 80.0)
    assert ("2026-10-14T22:42", 84.0) in rows  # special between routine obs
    assert len(rows) == 9


def test_parse_asos_csv_skips_missing_and_comments():
    text = ("#DEBUG: x\nstation,valid,tmpf\nMIA,2026-10-14 00:53,M\n"
            "MIA,2026-10-14 01:53,80.00\nMIA,2026-10-14 02:53,\n")
    assert iem.parse_asos_csv(text) == [("2026-10-14T01:53", 80.0)]


def test_asos_id_strips_k():
    assert iem.asos_id("KMIA") == "MIA"
    assert iem.asos_id("mia") == "MIA"
    assert iem.asos_id("PHNL") == "PHNL"


def test_fetch_hourly_temps_sends_exclusive_end_and_report_types():
    def handler(req):
        p = req.url.params
        assert p["station"] == "MIA" and p["data"] == "tmpf" and p["format"] == "onlycomma"
        assert p["tz"] == "America/New_York"
        assert (p["year1"], p["month1"], p["day1"]) == ("2026", "10", "14")
        assert (p["year2"], p["month2"], p["day2"]) == ("2026", "11", "1")  # Oct 31 inclusive
        assert p.get_list("report_type") == ["3", "4"]
        return httpx.Response(200, text=(FIX / "iem_asos.csv").read_text())
    rows = iem.fetch_hourly_temps("KMIA", "2026-10-14", "2026-10-31", "America/New_York",
                                  client=client_for(handler))
    assert rows[-1] == ("2026-10-14T23:53", 84.0)


def test_fetch_hourly_temps_retries_429():
    codes = iter([429, 429, 200])

    def handler(req):
        code = next(codes)
        return httpx.Response(code, text=(FIX / "iem_asos.csv").read_text() if code == 200 else "slow down")
    assert len(iem.fetch_hourly_temps("MIA", "2026-10-14", "2026-10-14", "America/New_York",
                                      client=client_for(handler))) == 9
