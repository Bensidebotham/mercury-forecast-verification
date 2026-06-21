"""CLOB client — public read-only order books (no auth).

There is intentionally no order-placement code in this module: the
project is paper-only until paper results justify a live pilot, and
the live pilot will target the Polymarket US API, not this one.
"""

import httpx

CLOB_BASE = "https://clob.polymarket.com"
UA = {"User-Agent": "Mozilla/5.0 (polybot paper-trading research)"}


def get_order_book(token_id: str) -> dict | None:
    """Fetch the order book for one outcome token.

    Returns {bids: [[price, size]...desc], asks: [[price, size]...asc],
             best_bid, best_ask, bid_depth, ask_depth} or None on error.
    """
    try:
        with httpx.Client(headers=UA, timeout=15) as client:
            resp = client.get(f"{CLOB_BASE}/book", params={"token_id": token_id})
            resp.raise_for_status()
            raw = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    bids = sorted(
        ([float(b["price"]), float(b["size"])] for b in raw.get("bids", [])),
        key=lambda x: -x[0],
    )
    asks = sorted(
        ([float(a["price"]), float(a["size"])] for a in raw.get("asks", [])),
        key=lambda x: x[0],
    )
    return {
        "bids": bids,
        "asks": asks,
        "best_bid": bids[0][0] if bids else None,
        "best_ask": asks[0][0] if asks else None,
        "bid_depth": bids[0][1] if bids else 0.0,
        "ask_depth": asks[0][1] if asks else 0.0,
    }
