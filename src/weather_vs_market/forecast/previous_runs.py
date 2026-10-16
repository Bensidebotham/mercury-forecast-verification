"""Archived deterministic forecasts by lead time, from Open-Meteo Previous Runs.

`temperature_2m_previous_dayN` is "the value predicted 24*N hours before valid
time". The daily max over lead-N hourly values is our retroactive "what the
model said N days out" for a market day. Caveat: each hour comes from a
different run (the one issued 24*N h before that hour), so a lead-1 day max
uses runs up to 23 h after local midnight of D-1. Pick leads with that
look-ahead in mind.

Two quirks drive the design:
- With timezone=<IANA zone>, Open-Meteo applies today's UTC offset to the
  whole range (EDT in January, 24 hours on DST days). So we request GMT and
  bucket hours into local days ourselves, which gives 23/25-hour DST days.
- One model returns unsuffixed keys (temperature_2m_previous_day1); several
  return per-model suffixes (..._previous_day1_gfs_seamless).

Coverage checked on 2026-10-16 (NYC): gfs_seamless (GFS + HRRR blended over CONUS)
starts 2021-03-23/24 and has a hole from 2023-12-29 to 2024-01-20. ecmwf_ifs025
starts 2024-02-03/04 with no gaps after. gfs025 is all null on this API, so use
gfs_seamless (or gfs_global for pure GFS).

There is no hard cap on the date range (5.75 years came back in one 2.6 s
request), but the free tier (600/min, 5,000/h, 10,000/day, non-commercial)
counts each 14 days per location, and each block of 10 variables, as another
call. A 366-day chunk costs ~26 calls (x1.4 with 14 variables), so we pause
between chunks to stay well under 600/min.
"""
import time
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from weather_vs_market import http

PREVIOUS_RUNS_BASE = "https://previous-runs-api.open-meteo.com/v1/forecast"
CHUNK_DAYS = 366
PAUSE_S = 6.0  # ~26-36 weighted calls per chunk -> <=360 calls/min
MAX_TRIES = 5
BACKOFF_S = 2.0


def _get_json(client: httpx.Client, url: str, params=None):
    return http.get(client, url, params, max_tries=MAX_TRIES, backoff_s=BACKOFF_S).json()


def _variable(lead: int) -> str:
    return "temperature_2m" if lead == 0 else f"temperature_2m_previous_day{lead}"


def _series_key(hourly: dict, lead: int, model: str, single_model: bool) -> str | None:
    suffixed = f"{_variable(lead)}_{model}"
    if suffixed in hourly:
        return suffixed
    # single-model responses drop the suffix
    plain = _variable(lead)
    return plain if single_model and plain in hourly else None


def _local_days(times: list[str], offset_s: int, tz: ZoneInfo | None) -> list[str]:
    if tz is None:
        return [t[:10] for t in times]
    shift = timedelta(seconds=offset_s)
    return [
        (datetime.fromisoformat(t).replace(tzinfo=UTC) - shift).astimezone(tz).date().isoformat()
        for t in times
    ]


def _hours_in_day(day: str, tz: ZoneInfo | None) -> int:
    if tz is None:
        return 24
    start = datetime.fromisoformat(day).replace(tzinfo=tz)
    end = (start + timedelta(days=1)).replace(tzinfo=tz)
    return round((end.timestamp() - start.timestamp()) / 3600)


def parse_daily_max(payload: dict, leads: Sequence[int], models: Sequence[str],
                    tz: str | None = None) -> dict[tuple[str, str, int], float]:
    """{(local YYYY-MM-DD, model, lead): max hourly value} for complete days only.

    With tz, hours are converted from the payload's offset (request GMT) into
    local days, and a day must have all its 23/24/25 hours. Without tz, the
    payload's own date strings are used and a day needs 24 hours. A day with
    any null, or with missing hours, is dropped rather than giving a partial max.
    """
    hourly = payload.get("hourly") or {}
    zone = ZoneInfo(tz) if tz else None
    days = _local_days(hourly.get("time") or [], int(payload.get("utc_offset_seconds") or 0), zone)
    out: dict[tuple[str, str, int], float] = {}
    for model in models:
        for lead in leads:
            key = _series_key(hourly, lead, model, single_model=len(models) == 1)
            if key is None:
                continue
            by_day: dict[str, list] = defaultdict(list)
            for day, value in zip(days, hourly[key], strict=True):
                by_day[day].append(value)
            for day, values in by_day.items():
                if len(values) == _hours_in_day(day, zone) and all(v is not None for v in values):
                    out[(day, model, lead)] = float(max(values))
    return out


def _chunks(start: date, end: date) -> list[tuple[date, date]]:
    out, lo = [], start
    while lo <= end:
        hi = min(lo + timedelta(days=CHUNK_DAYS - 1), end)
        out.append((lo, hi))
        lo = hi + timedelta(days=1)
    return out


def fetch_daily_max_by_lead(lat: float, lon: float, tz: str, start_date: str, end_date: str,
                            leads: Sequence[int] = (1, 2),
                            models: Sequence[str] = ("gfs_seamless", "ecmwf_ifs025"),
                            client: httpx.Client | None = None) -> dict[tuple[str, str, int], float]:
    """(local date, model, lead_days) -> forecast daily max (°F) over [start_date, end_date]."""
    first, last = date.fromisoformat(start_date), date.fromisoformat(end_date)
    out: dict[tuple[str, str, int], float] = {}
    with http.session(client) as c:
        for i, (lo, hi) in enumerate(_chunks(first, last)):
            if i:
                time.sleep(PAUSE_S)
            # local days straddle UTC dates, so pad the GMT request by a day each side
            payload = _get_json(c, PREVIOUS_RUNS_BASE, {
                "latitude": lat, "longitude": lon, "timezone": "GMT",
                "temperature_unit": "fahrenheit",
                "start_date": (lo - timedelta(days=1)).isoformat(),
                "end_date": (hi + timedelta(days=1)).isoformat(),
                "models": ",".join(models),
                "hourly": ",".join(_variable(n) for n in leads),
            })
            for key, value in parse_daily_max(payload, leads, models, tz).items():
                if lo.isoformat() <= key[0] <= hi.isoformat():
                    out[key] = value
    return out
