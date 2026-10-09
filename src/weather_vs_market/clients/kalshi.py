"""Keyless Kalshi market-data client for daily high-temperature markets.

Market data requires no auth. Endpoints/fields per https://docs.kalshi.com (v2).
Pure helpers (market_prob_from_quote, market_to_unified) are network-free and unit-tested;
fetch_* wrap httpx and are exercised in integration, not unit, tests.
"""
from datetime import datetime, timezone

import httpx

from weather_vs_market.model.kalshi_buckets import parse_kalshi_strike

BASE = "https://api.elections.kalshi.com/trade-api/v2"
CITY_SERIES = {
    "New York": "KXHIGHNY", "Los Angeles": "KXHIGHLAX", "Chicago": "KXHIGHCHI",
    "Miami": "KXHIGHMIA", "Austin": "KXHIGHAUS", "Denver": "KXHIGHDEN",
    "Philadelphia": "KXHIGHPHIL", "Houston": "KXHIGHHOU",
}

def market_prob_from_quote(yes_bid: float | None, yes_ask: float | None) -> float | None:
    vals = [v for v in (yes_bid, yes_ask) if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals) / 100.0, 4)

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
        "unit": unit, "question": f"{raw.get('title') or ''} {label}".strip(),
        "close_ts": _close_ts(raw["close_time"]),
        "yes_bid": raw.get("yes_bid"), "yes_ask": raw.get("yes_ask"),
        "status": raw.get("status"), "result": raw.get("result"),
    }

def _normalize_market(m: dict) -> dict:
    """Normalise API response to canonical field names used by market_to_unified.

    The Kalshi v2 API returns prices as dollar strings in ``yes_bid_dollars`` /
    ``yes_ask_dollars`` (e.g. ``"0.0500"``) and leaves ``yes_bid``/``yes_ask``
    null.  We convert to integer cents so that
    ``market_prob_from_quote`` and callers downstream receive consistent values.
    """
    out = dict(m)
    for side in ("yes_bid", "yes_ask"):
        dollars_key = f"{side}_dollars"
        if out.get(side) is None and dollars_key in out:
            raw_val = out[dollars_key]
            try:
                out[side] = round(float(raw_val) * 100)
            except (TypeError, ValueError):
                out[side] = None
    return out

def fetch_markets(series_ticker: str, status: str = "open",
                  client: httpx.Client | None = None) -> list[dict]:
    own = client is None
    client = client or httpx.Client(timeout=20)
    try:
        r = client.get(f"{BASE}/markets",
                       params={"series_ticker": series_ticker, "status": status, "limit": 1000})
        r.raise_for_status()
        return [_normalize_market(m) for m in r.json().get("markets", [])]
    finally:
        if own:
            client.close()

def fetch_settled(series_ticker: str, client: httpx.Client | None = None) -> list[dict]:
    """Resolved markets carry result='yes'|'no' — used for backfill."""
    return fetch_markets(series_ticker, status="settled", client=client)
