"""Keyless Kalshi market-data client for daily high-temperature markets.

Market data requires no auth. Endpoints/fields per https://docs.kalshi.com (v2).
Pure helpers (market_prob_from_quote, market_to_unified) are network-free and unit-tested.
"""
from datetime import datetime

import httpx

from weather_vs_market.model.kalshi_buckets import parse_kalshi_strike

BASE = "https://api.elections.kalshi.com/trade-api/v2"
CITY_SERIES = {
    "New York": "KXHIGHNY", "Los Angeles": "KXHIGHLAX", "Chicago": "KXHIGHCHI",
    "Miami": "KXHIGHMIA", "Austin": "KXHIGHAUS", "Denver": "KXHIGHDEN",
    "Philadelphia": "KXHIGHPHIL", "Houston": "KXHIGHHOU",
}

def market_prob_from_quote(yes_bid: float | None, yes_ask: float | None) -> float | None:
    """Mid of a two-sided YES book, in dollars. A one-sided book is not a price."""
    if yes_bid is None or yes_ask is None:
        return None
    return round((yes_bid + yes_ask) / 2, 4)

def _close_ts(close_time: str) -> float:
    return datetime.fromisoformat(close_time.replace("Z", "+00:00")).timestamp()

def _bucket_from_strikes(raw: dict) -> tuple[float | None, float | None] | None:
    """Bucket bounds from Kalshi's structured strike fields.

    Daily highs are reported in whole degrees, so a strict ">73" is "74 or
    above" and "<66" is "65 or below"; "between" strikes are already inclusive.
    """
    kind, floor, cap = raw.get("strike_type"), raw.get("floor_strike"), raw.get("cap_strike")
    if kind == "between" and floor is not None and cap is not None:
        return float(floor), float(cap)
    if kind == "greater" and floor is not None:
        return float(floor) + 1, None
    if kind == "less" and cap is not None:
        return None, float(cap) - 1
    return None

def market_to_unified(raw: dict, city: str, target_date: str) -> dict | None:
    raw = _normalize_market(raw)
    label = raw.get("subtitle") or raw.get("yes_sub_title") or ""
    strikes = _bucket_from_strikes(raw)
    if strikes is not None:
        (lo, hi), unit = strikes, "F"
    else:
        bucket = parse_kalshi_strike(label)
        if bucket is None:
            return None
        lo, hi, unit = bucket
    ticker = raw["ticker"]
    return {
        "market_uid": f"kalshi:{ticker}", "venue": "kalshi", "external_id": ticker,
        "city": city, "target_date": target_date, "bucket_lo": lo, "bucket_hi": hi,
        "event_key": raw.get("event_ticker"),
        "unit": unit, "question": f"{raw.get('title') or ''} {label}".strip(),
        "close_ts": _close_ts(raw["close_time"]),
        "yes_bid": raw.get("yes_bid"), "yes_ask": raw.get("yes_ask"),
        "status": raw.get("status"), "result": raw.get("result"),
    }

def _normalize_market(m: dict) -> dict:
    """Normalize quotes to dollars in [0, 1].

    Current v2 payloads leave ``yes_bid``/``yes_ask`` null and put prices in
    ``yes_bid_dollars``/``yes_ask_dollars`` strings (e.g. ``"0.0500"``); older
    payloads used integer cents.
    """
    out = dict(m)
    for side in ("yes_bid", "yes_ask"):
        dollars = out.get(f"{side}_dollars")
        try:
            if dollars is not None:
                out[side] = float(dollars)
            elif out.get(side) is not None:
                out[side] = out[side] / 100.0
        except (TypeError, ValueError):
            out[side] = None
    return out

def fetch_markets(series_ticker: str, status: str = "open",
                  client: httpx.Client | None = None) -> list[dict]:
    """All markets in a series with the given status, following the cursor."""
    own = client is None
    client = client or httpx.Client(timeout=20)
    markets: list[dict] = []
    cursor = ""
    try:
        while True:
            params = {"series_ticker": series_ticker, "status": status, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            r = client.get(f"{BASE}/markets", params=params)
            r.raise_for_status()
            body = r.json()
            page = body.get("markets", [])
            markets += page
            cursor = body.get("cursor") or ""
            if not cursor or not page:
                return markets
    finally:
        if own:
            client.close()


def fetch_settled(series_ticker: str, client: httpx.Client | None = None) -> list[dict]:
    """Recently settled markets (result = 'yes' | 'no'). Older ones are on the
    /historical endpoints, see clients/kalshi_history.py."""
    return fetch_markets(series_ticker, status="settled", client=client)
