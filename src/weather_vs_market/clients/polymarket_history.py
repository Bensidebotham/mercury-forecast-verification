"""Closed Polymarket daily-high events and their CLOB price history, for backtests.

Slugs are not a stable key. Before 2026-02-03 they have no year
("...-on-march-1"), and in Jan-Feb 2025 some use short months ("...-on-feb-14",
"...-on-jan-23-25"). A few carry a random suffix ("...-on-february-1-777",
"...-on-may-8-625", which is the May 9 event), and a no-year slug can resolve
to a different year than the one asked for. From 2026-02-03 they end in "-YYYY".
So the reliable way to list history is by series (fetch_series_events), keying
each event by the date in its title. event_slug/find_event cover one-off lookups.

The same date can also have two events: on 2026-05-19 every city has an
"arch-" event (the real one, listed two days ahead) plus a relisting created
after the day with wrong buckets. dedupe_by_date keeps the earliest-listed one.

Depth (series start): NYC 2025-01-22, Chicago/Miami 2025-12-04 (then a gap to
2026-01-22), LA/SF 2026-03-24. Settlement stations are KLGA, KORD, KMIA, KLAX
and KSFO, read from `resolutionSource`. That field is empty before Dec 2025, holds
a Wunderground URL until 2026-08-22 and a weather.gov timeseries URL after, so
the description is the fallback.

The CLOB returns an empty history for closed markets with interval=max/1w
(recent ones still work), so we always send explicit startTs/endTs. Windows
longer than 15 days are rejected with a 400, so longer ranges are chunked.
"""
import json
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
UA = {"User-Agent": "weather-vs-market/0.3 (github.com/Bensidebotham/weather-vs-market)"}
CITY_SERIES = {
    "nyc": "nyc-daily-weather", "chicago": "chicago-daily-weather", "miami": "miami-daily-weather",
    "los-angeles": "los-angeles-daily-weather", "san-francisco": "san-francisco-daily-weather",
}
YEAR_SUFFIX_FROM = date(2026, 2, 3)
MAX_WINDOW_S = 15 * 86400
PAGE = 100  # Gamma caps /events pages at 100 whatever `limit` says
MAX_TRIES = 5
BACKOFF_S = 1.0

MONTHS = ("january february march april may june july august "
          "september october november december").split()
_MONTH_NUM = {m: i + 1 for i, m in enumerate(MONTHS)} | {m[:3]: i + 1 for i, m in enumerate(MONTHS)}
_MONTH_NUM["sept"] = 9
_TITLE_RE = re.compile(r"Highest temperature in .+ on ([A-Za-z]+)\.? (\d{1,2})\?", re.IGNORECASE)
_SITE_RE = re.compile(r"[?&]site=([A-Za-z0-9]{3,5})\b")
# .../history/daily/us/ny/new-york-city/KLGA, and in Dec 2025 .../weather/KORD
_WU_RE = re.compile(r"wunderground\.com/[\w/-]*?/([A-Z0-9]{4})\b")


@contextmanager
def _session(client: httpx.Client | None) -> Iterator[httpx.Client]:
    if client is not None:
        yield client
        return
    with httpx.Client(timeout=30) as own:
        yield own


def _get_json(client: httpx.Client, url: str, params: dict | None = None):
    """GET with retries on 429/5xx/transport errors; other 4xx raise at once."""
    for attempt in range(MAX_TRIES):
        last = attempt == MAX_TRIES - 1
        try:
            resp = client.get(url, params=params, headers=UA)
        except httpx.TransportError:
            if last:
                raise
            time.sleep(BACKOFF_S * 2**attempt)
            continue
        if (resp.status_code == 429 or resp.status_code >= 500) and not last:
            time.sleep(BACKOFF_S * 2**attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    raise AssertionError("unreachable")


def _iso_ts(raw: str | None) -> float | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00").replace(" ", "T")).timestamp()


# --- slugs and event lookup -------------------------------------------------

def event_slug(city_slug: str, d: date) -> str:
    """The slug Polymarket used for this date's event under its usual pattern."""
    base = f"highest-temperature-in-{city_slug}-on-{MONTHS[d.month - 1]}-{d.day}"
    return f"{base}-{d.year}" if d >= YEAR_SUFFIX_FROM else base


def candidate_slugs(city_slug: str, d: date) -> list[str]:
    """Usual slug first, then the other known patterns for that date."""
    month = MONTHS[d.month - 1]
    stem = f"highest-temperature-in-{city_slug}-on-"
    out = [event_slug(city_slug, d), f"{stem}{month}-{d.day}-{d.year}", f"{stem}{month}-{d.day}",
           f"{stem}{month[:3]}-{d.day}", f"{stem}{month[:3]}-{d.day}-{d.year % 100}"]
    return list(dict.fromkeys(out))


def fetch_event(slug: str, client: httpx.Client | None = None) -> dict | None:
    with _session(client) as c:
        events = _get_json(c, f"{GAMMA_BASE}/events", {"slug": slug})
    return events[0] if events else None


def find_event(city_slug: str, d: date, client: httpx.Client | None = None) -> dict | None:
    """First candidate-slug event whose title date is d (no-year slugs can hit another year)."""
    with _session(client) as c:
        for slug in candidate_slugs(city_slug, d):
            ev = fetch_event(slug, client=c)
            if ev and event_date(ev) == d:
                return ev
    return None


def fetch_series_events(series_slug: str, client: httpx.Client | None = None) -> list[dict]:
    """Every event in a Gamma series (e.g. "nyc-daily-weather"), markets included."""
    out: list[dict] = []
    with _session(client) as c:
        while True:
            page = _get_json(c, f"{GAMMA_BASE}/events",
                             {"series_slug": series_slug, "limit": PAGE, "offset": len(out)})
            if not page:
                return out
            out.extend(page)


# --- pure parsing -----------------------------------------------------------

def event_date(ev: dict) -> date | None:
    """Target date from the title ("... on May 9?"), with the year taken from
    eventDate/endDate/startDate. endDate alone is unreliable (May 12 ends May 13)."""
    m = _TITLE_RE.search(ev.get("title") or "")
    if not m:
        return None
    month = _MONTH_NUM.get(m.group(1).lower())
    anchor = ev.get("eventDate") or ev.get("endDate") or ev.get("startDate")
    if not month or not anchor:
        return None
    ref = date.fromisoformat(anchor[:10])
    options = [date(y, month, int(m.group(2))) for y in (ref.year - 1, ref.year, ref.year + 1)]
    return min(options, key=lambda d: abs((d - ref).days))


def resolution_station(ev: dict) -> str | None:
    """ICAO id of the settlement station, e.g. "site=klga" -> "KLGA"."""
    for text in (ev.get("resolutionSource") or "", ev.get("description") or ""):
        m = _SITE_RE.search(text) or _WU_RE.search(text)
        if m:
            return m.group(1).upper()
    return None


def resolved_outcome(outcome_prices: list, closed: bool) -> int | None:
    if not closed or not outcome_prices:
        return None
    yes = float(outcome_prices[0])
    return 1 if yes >= 0.99 else 0 if yes <= 0.01 else None


def parse_event(ev: dict) -> list[dict]:
    """One row per bucket market: YES token, bucket text, outcome, station, end_ts."""
    station, target = resolution_station(ev), event_date(ev)
    rows = []
    for mkt in ev.get("markets") or []:
        tokens = json.loads(mkt.get("clobTokenIds") or "[]")
        if not tokens:
            continue
        closed = bool(mkt.get("closed"))
        rows.append({
            "token_id": tokens[0],
            "event_slug": ev.get("slug"),
            "target_date": target.isoformat() if target else None,
            "question": mkt.get("question") or "",
            "bucket": mkt.get("groupItemTitle") or "",
            "closed": closed,
            "outcome": resolved_outcome(json.loads(mkt.get("outcomePrices") or "[]"), closed),
            "end_ts": _iso_ts(mkt.get("endDate") or ev.get("endDate")),
            "station": station,
        })
    return rows


def dedupe_by_date(events: list[dict]) -> dict[date, dict]:
    """One event per target date; on a clash keep the earliest-listed event."""
    out: dict[date, dict] = {}
    for ev in sorted(events, key=lambda e: e.get("startDate") or e.get("creationDate") or ""):
        d = event_date(ev)
        if d is not None and d not in out:
            out[d] = ev
    return out


def parse_price_history(payload: dict) -> list[tuple[int, float]]:
    return [(int(p["t"]), float(p["p"])) for p in payload.get("history") or []]


# --- price history ----------------------------------------------------------

def fetch_price_history(token: str, start_ts: int, end_ts: int, fidelity: int = 60,
                        client: httpx.Client | None = None) -> list[tuple[int, float]]:
    """(ts, YES price) points for one token, chunked into <=15-day windows."""
    points: dict[int, float] = {}
    with _session(client) as c:
        lo = int(start_ts)
        while lo < end_ts:
            hi = min(lo + MAX_WINDOW_S, int(end_ts))
            payload = _get_json(c, f"{CLOB_BASE}/prices-history",
                                {"market": token, "startTs": lo, "endTs": hi, "fidelity": fidelity})
            points.update(parse_price_history(payload))
            lo = hi
    return sorted(points.items())
