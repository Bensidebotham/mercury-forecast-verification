"""CLOB client wrapper.

Phases 1-3 use only public endpoints (order books, prices) — no keys.
Phase 4+ adds L2 auth: one-time L1 wallet signature derives API
key/secret/passphrase, then HMAC-SHA256 per request; each order is
EIP-712 signed locally. SDK: py-clob-client v2 (or newer py-sdk —
evaluate before wiring up).
"""

CLOB_BASE = "https://clob.polymarket.com"


def get_order_book(token_id: str) -> dict:
    """Fetch the full order book for one outcome token.

    TODO(phase 1): GET /book?token_id=... — return bids/asks with sizes.
    """
    raise NotImplementedError


def get_authed_client():
    """Build an authenticated client for order placement (phase 4+).

    TODO(phase 4): derive L2 creds from POLYMARKET_PRIVATE_KEY,
    return SDK client. Refuse to construct if quoting.paper is true.
    """
    raise NotImplementedError
