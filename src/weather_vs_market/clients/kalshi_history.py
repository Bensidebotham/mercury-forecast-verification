"""Settled Kalshi temperature markets and their hourly quotes, for backtests.

Kalshi splits its archive at a moving cutoff (GET /historical/cutoff,
`market_settled_ts`). Markets settled before it are served from /historical/*,
which goes back to the first daily-high markets (NY Dec 2022, MIA May 2023;
pre-2024 tickers use the old "HIGHMIA-" prefix and are still returned for
series KXHIGHMIA). Newer ones live under /markets and /series/*. A few days
around the cutoff appear in both lists, so we dedupe by ticker.

Candle routing is decided from the cutoff, not by catching 404s: a market
settled before the cutoff is fetched from /historical/markets/{ticker}/candlesticks
(the series path 404s for anything older than about a week before the cutoff),
everything else from /series/{series}/markets/{ticker}/candlesticks (which
404s on the historical path). The two candle schemas differ: live candles carry
`yes_bid.close_dollars`, historical ones `yes_bid.close`. parse_candles accepts both.

Read-only, no auth. The public tier 429s at roughly 7 req/s sustained (burst of
~10, no Retry-After header), so requests are paced and 429/5xx retried with
exponential backoff. One request returns at most 5000 candles (more is a 400).
Measured 2026-10-16: all 7.5k KXHIGHMIA markets in 10 requests (~2 s);
hourly candles for 100 markets in ~24 s, with 3 retried 429s.
"""
from datetime import datetime

import httpx

from weather_vs_market import http

BASE = "https://api.elections.kalshi.com/trade-api/v2"
MAX_CANDLES = 5000
MAX_TRIES = 5
BACKOFF_S = 1.0
MIN_INTERVAL_S = 0.2  # ~5 req/s, under the observed ~7 req/s limit

_PACER = http.Pacer(MIN_INTERVAL_S)


def _get_json(client: httpx.Client, url: str, params=None):
    return http.get(client, url, params, pacer=_PACER, max_tries=MAX_TRIES, backoff_s=BACKOFF_S).json()


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def fetch_cutoff(client: httpx.Client | None = None) -> float:
    """Epoch seconds of the historical/live split for settled markets."""
    with http.session(client) as c:
        return _ts(_get_json(c, f"{BASE}/historical/cutoff")["market_settled_ts"])


def _paginate(client: httpx.Client, path: str, params: dict) -> list[dict]:
    out: list[dict] = []
    cursor = None
    while True:
        page = _get_json(client, f"{BASE}{path}", {**params, **({"cursor": cursor} if cursor else {})})
        markets = page.get("markets") or []
        out.extend(markets)
        cursor = page.get("cursor")
        if not cursor or not markets:
            return out


def fetch_settled_markets(series: str, client: httpx.Client | None = None) -> list[dict]:
    """Every settled market in the series, historical and live, oldest first.

    Raw Kalshi dicts (ticker, event_ticker, strike_type, floor_strike,
    cap_strike, open_time, close_time, settlement_ts, result, ...). Pre-2024
    markets may have null strike fields; their bucket is in the title only.
    """
    with http.session(client) as c:
        hist = _paginate(c, "/historical/markets", {"series_ticker": series, "limit": 1000})
        live = _paginate(c, "/markets", {"series_ticker": series, "status": "settled", "limit": 1000})
    by_ticker = {m["ticker"]: m for m in hist}
    by_ticker.update({m["ticker"]: m for m in live})
    return sorted(by_ticker.values(), key=lambda m: (m.get("close_time") or "", m["ticker"]))


def is_historical(market: dict, cutoff_ts: float) -> bool:
    """True if the market's candles must come from the /historical endpoint."""
    settled = market.get("settlement_ts") or market.get("close_time")
    return settled is not None and _ts(settled) < cutoff_ts


def _dollars(side: dict | None) -> float | None:
    if not side:
        return None
    raw = side.get("close_dollars", side.get("close"))
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def parse_candles(payload: dict) -> list[dict]:
    """[{ts, yes_bid, yes_ask}] in [0, 1] from either candle schema, by ts.

    An empty book side is reported by Kalshi as bid 0 / ask 1, not null; that
    is passed through. None means the field was absent.
    """
    rows = [
        {"ts": int(c["end_period_ts"]), "yes_bid": _dollars(c.get("yes_bid")),
         "yes_ask": _dollars(c.get("yes_ask"))}
        for c in payload.get("candlesticks") or []
    ]
    return sorted(rows, key=lambda r: r["ts"])


def _windows(start_ts: int, end_ts: int, period_s: int) -> list[tuple[int, int]]:
    span = MAX_CANDLES * period_s
    out, lo = [], start_ts
    while lo < end_ts:
        hi = min(lo + span, end_ts)
        out.append((lo, hi))
        lo = hi
    return out or [(start_ts, end_ts)]


def fetch_hourly_quotes(series: str, ticker: str, start_ts: int, end_ts: int, historical: bool,
                        client: httpx.Client | None = None) -> list[dict]:
    """Hourly yes bid/ask closes for one market. Use is_historical() for the flag."""
    path = (f"/historical/markets/{ticker}/candlesticks" if historical
            else f"/series/{series}/markets/{ticker}/candlesticks")
    by_ts: dict[int, dict] = {}
    with http.session(client) as c:
        for lo, hi in _windows(int(start_ts), int(end_ts), 3600):
            payload = _get_json(c, f"{BASE}{path}",
                                {"start_ts": lo, "end_ts": hi, "period_interval": 60})
            by_ts.update({r["ts"]: r for r in parse_candles(payload)})
    return [by_ts[t] for t in sorted(by_ts)]
