"""Gamma API client — market discovery (read-only, no auth).

Public international endpoints, used for paper-trading market data.
When the Polymarket US API key is available, a clients/us.py with the
same return shape replaces this for the live pilot.
"""

import json
import re
from datetime import datetime, timezone

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"
UA = {"User-Agent": "polybot/0.1 (paper trading research)"}

# "Highest temperature in NYC on June 10?"
_EVENT_RE = re.compile(r"Highest temperature in (.+) on (\w+ \d+)\?")

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        "January February March April May June July August September October November December".split()
    )
}


def _parse_event_title(title: str, year: int) -> tuple[str, str] | None:
    """Return (city_text, YYYY-MM-DD) or None if not a daily-high event."""
    m = _EVENT_RE.match(title)
    if not m:
        return None
    city_text = m.group(1)
    month_name, day = m.group(2).rsplit(" ", 1)
    month = _MONTHS.get(month_name)
    if not month:
        return None
    return city_text, f"{year:04d}-{month:02d}-{int(day):02d}"


def find_weather_markets(cities: list, limit: int = 50) -> list[dict]:
    """Return active daily-high temperature markets for configured cities.

    Output rows: {token_id, event_slug, city, target_date, question,
                  outcome_prices, end_ts, closed}
    Bucket bounds are parsed downstream by model.buckets.parse_bucket.
    """
    with httpx.Client(headers=UA, timeout=20) as client:
        resp = client.get(
            f"{GAMMA_BASE}/events",
            params={
                "closed": "false",
                "tag_slug": "weather",
                "limit": limit,
                "order": "volume24hr",
                "ascending": "false",
            },
        )
        resp.raise_for_status()
        events = resp.json()

    year = datetime.now(timezone.utc).year
    alias_to_city = {}
    for c in cities:
        for a in c.aliases or [c.name]:
            alias_to_city[a.lower()] = c.name

    rows = []
    for ev in events:
        parsed = _parse_event_title(ev.get("title", ""), year)
        if not parsed:
            continue
        city_text, target_date = parsed
        city = alias_to_city.get(city_text.lower())
        if not city:
            continue
        for mkt in ev.get("markets", []):
            token_ids = json.loads(mkt.get("clobTokenIds") or "[]")
            if not token_ids:
                continue
            end_ts = None
            if mkt.get("endDate"):
                end_ts = datetime.fromisoformat(
                    mkt["endDate"].replace("Z", "+00:00")
                ).timestamp()
            rows.append(
                {
                    "token_id": token_ids[0],  # YES token
                    "event_slug": ev.get("slug", ""),
                    "city": city,
                    "target_date": target_date,
                    "question": mkt.get("question", ""),
                    "outcome_prices": json.loads(mkt.get("outcomePrices") or "[]"),
                    "end_ts": end_ts,
                    "closed": bool(mkt.get("closed")),
                }
            )
    return rows


def get_event_resolutions(slugs: list[str]) -> dict[str, int | None]:
    """Resolve outcomes for all markets in the given events.

    Returns {yes_token_id: 1|0|None}. Queried by event slug because the
    /markets?clob_token_ids lookup stops returning archived markets.
    """
    out: dict[str, int | None] = {}
    with httpx.Client(headers=UA, timeout=20) as client:
        for slug in set(slugs):
            try:
                resp = client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
                resp.raise_for_status()
                events = resp.json()
            except (httpx.HTTPError, ValueError):
                continue
            for ev in events:
                for m in ev.get("markets", []):
                    token_ids = json.loads(m.get("clobTokenIds") or "[]")
                    prices = json.loads(m.get("outcomePrices") or "[]")
                    if not token_ids or not prices:
                        continue
                    if m.get("closed"):
                        yes = float(prices[0])
                        out[token_ids[0]] = 1 if yes > 0.9 else 0 if yes < 0.1 else None
                    else:
                        out[token_ids[0]] = None
    return out
