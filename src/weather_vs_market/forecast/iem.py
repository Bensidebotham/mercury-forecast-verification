"""Settlement truth and observed temperatures from the Iowa Environmental Mesonet.

The NWS CLI daily climate report is what Kalshi settles on, and IEM archives
it as JSON per station-year (4-letter ICAO ids; a 3-letter id is a 422 and an
unknown one returns no rows). A missing high is the string "M". Some rows
come from an afternoon preliminary CLI, issued before the day ended, so the
high covers only part of the day. That is true of today's row, and of the odd past row the
final never replaced (KMIA 2026-02-21, issued 16:23 local). Pass tz to
fetch_cli_highs to drop those rows.

Hourly METARs come from asos.py (3-letter id, e.g. MIA). report_type=3 is the
routine hourly ob (:53 past) and 4 the specials, which catch peaks between
hours. 1 is 5-minute HFMETAR, which has no tmpf. day2 is exclusive, so we send
end_date + 1. IEM throttles to 1 request/s per IP (429) and caps a request
at 1,000 station-years, so we pace at 1 s and never need to chunk one station.
"""
import csv
import io
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from weather_vs_market import http

IEM_BASE = "https://mesonet.agron.iastate.edu"
CLI_URL = f"{IEM_BASE}/json/cli.py"
ASOS_URL = f"{IEM_BASE}/cgi-bin/request/asos.py"
ROUTINE, SPECIAL = 3, 4
MIN_INTERVAL_S = 1.0
MAX_TRIES = 5
BACKOFF_S = 2.0

# --- NWS CLI daily highs ------------------------------------------------------

_PACER = http.Pacer(MIN_INTERVAL_S)


def _get(client: httpx.Client, url: str, params) -> httpx.Response:
    return http.get(client, url, params, pacer=_PACER, max_tries=MAX_TRIES, backoff_s=BACKOFF_S)


def _issued_utc(product: str) -> datetime | None:
    """CLI product ids start with the UTC issue time: "202610162033-KOKX-CDUS41-CLINYC"."""
    try:
        return datetime.strptime(product[:12], "%Y%m%d%H%M").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _is_final(row: dict, tz: ZoneInfo) -> bool:
    issued = _issued_utc(row.get("product") or "")
    day_end = datetime.fromisoformat(row["valid"]).replace(tzinfo=tz) + timedelta(days=1)
    return issued is not None and issued >= day_end


def parse_cli_highs(payload: dict, tz: str | None = None) -> dict[str, int]:
    """{YYYY-MM-DD: high °F}. "M"/null highs are skipped.

    With tz (the station's zone), rows from a CLI issued before that local day
    ended are skipped too, because they hold a partial-day high.
    """
    zone = ZoneInfo(tz) if tz else None
    out: dict[str, int] = {}
    for row in payload.get("results") or []:
        high = row.get("high")
        if not isinstance(high, (int, float)) or isinstance(high, bool):
            continue
        if zone is not None and not _is_final(row, zone):
            continue
        out[row["valid"]] = int(high)
    return out


def fetch_cli_highs(station: str, year: int, client: httpx.Client | None = None,
                    *, tz: str | None = None) -> dict[str, int]:
    """CLI daily highs for a 4-letter station (KNYC, KMDW, KLGA, ...) and year."""
    with http.session(client) as c:
        payload = _get(c, CLI_URL, {"station": station, "year": year}).json()
    return parse_cli_highs(payload, tz)


# --- hourly METAR temperatures --------------------------------------------------

def parse_asos_csv(text: str) -> list[tuple[str, float]]:
    """[(local "YYYY-MM-DDTHH:MM", °F)] from asos.py onlycomma output, "M" skipped."""
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    out = []
    for row in csv.DictReader(io.StringIO("\n".join(lines))):
        raw = (row.get("tmpf") or "").strip()
        try:
            value = float(raw)
        except ValueError:
            continue
        out.append((row["valid"].replace(" ", "T"), value))
    return out


def asos_id(station: str) -> str:
    """IEM's ASOS id: drop the K from 4-letter CONUS ICAO codes (KMIA -> MIA)."""
    s = station.upper()
    return s[1:] if len(s) == 4 and s.startswith("K") else s


def fetch_hourly_temps(station: str, start_date: str, end_date: str, tz: str,
                       client: httpx.Client | None = None) -> list[tuple[str, float]]:
    """Routine + special METAR temps, start_date..end_date inclusive, local time.

    Timestamps are local wall time without an offset, so the repeated hour
    on the autumn DST change shows up twice.
    """
    first = date.fromisoformat(start_date)
    stop = date.fromisoformat(end_date) + timedelta(days=1)
    params = [
        ("station", asos_id(station)), ("data", "tmpf"), ("tz", tz), ("format", "onlycomma"),
        ("year1", first.year), ("month1", first.month), ("day1", first.day),
        ("year2", stop.year), ("month2", stop.month), ("day2", stop.day),
        ("report_type", ROUTINE), ("report_type", SPECIAL),
    ]
    with http.session(client) as c:
        return parse_asos_csv(_get(c, ASOS_URL, params).text)
