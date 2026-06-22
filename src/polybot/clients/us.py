"""Polymarket US client — authenticated access to the CFTC-regulated API.

Two hosts, both Ed25519-signed (anonymous access is unreliable):
  - api.polymarket.us      : account / portfolio / (future) trading
  - gateway.polymarket.us  : market data (search, order books, settlement)

Market-data methods are normalized to the SAME return shapes the PaperEngine
already consumes from gamma.py/clob.py, with the bucket market *slug* used as
the engine's opaque token id. Scope is read-only: no order placement until
paper results justify a live pilot.
"""

import base64
import json
import time
from datetime import datetime, timezone

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519

from polybot.clients.gamma import build_alias_map, parse_event_title
from polybot.config import Credentials, load_credentials
from polybot.model.buckets import parse_us_bucket

US_BASE = "https://api.polymarket.us"
US_GATEWAY = "https://gateway.polymarket.us"


# ---------- pure normalizers (unit-tested offline) ----------

def _normalize_book(raw: dict) -> dict | None:
    """Map a gateway /book payload to the engine's order-book shape."""
    md = raw.get("marketData") if isinstance(raw, dict) else None
    if not md:
        return None
    bids = sorted(
        ([float(b["px"]["value"]), float(b["qty"])] for b in md.get("bids", [])),
        key=lambda x: -x[0],
    )
    asks = sorted(
        ([float(o["px"]["value"]), float(o["qty"])] for o in md.get("offers", [])),
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


def _parse_reward_params(raw: dict) -> dict | None:
    """Extract normalized liquidity-reward params, or None if not reward-eligible.

    Key names below mirror the probe output (scripts/probe_rewards_api.py); update
    them here if the live API differs. This is the ONLY API-shape-dependent code."""
    rw = raw.get("rewards") if isinstance(raw, dict) else None
    if not rw:
        return None
    try:
        return {
            "pool_usd": float(rw["dailyPoolUsd"]),
            "discount": float(rw["discountFactor"]),
            "target_size": float(rw["targetSize"]),
            "max_spread": float(rw["maxSpread"]),
            "min_size": float(rw["minSize"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _normalize_reward_market(raw: dict) -> dict | None:
    """Map one raw market payload to the internal reward-market contract."""
    slug = raw.get("slug")
    if not slug:
        return None
    end_ts = None
    if raw.get("endDate"):
        end_ts = datetime.fromisoformat(
            raw["endDate"].replace("Z", "+00:00")
        ).timestamp()
    return {
        "token_id": slug,
        "event_slug": raw.get("eventSlug", ""),
        "category": raw.get("category", ""),
        "question": raw.get("title", ""),
        "end_ts": end_ts,
        "closed": bool(raw.get("closed")),
        "reward": _parse_reward_params(raw),
    }


def _event_to_rows(event: dict, alias_to_city: dict[str, str], year: int) -> list[dict]:
    """Expand one climate event into per-bucket market rows.

    Row shape matches gamma.find_weather_markets plus pre-parsed bucket bounds
    (bucket_lo/bucket_hi/unit), so the engine can skip parse_bucket. token_id is
    the bucket slug — the key used for book lookups and settlement.
    """
    parsed = parse_event_title(event.get("title", ""), year)
    if not parsed:
        return []
    city_text, target_date = parsed
    city = alias_to_city.get(city_text.lower())
    if not city:
        return []

    end_ts = None
    if event.get("endDate"):
        end_ts = datetime.fromisoformat(
            event["endDate"].replace("Z", "+00:00")
        ).timestamp()
    event_closed = bool(event.get("closed"))

    rows = []
    for mkt in event.get("markets", []) or []:
        label = mkt.get("titleShort") or mkt.get("title") or ""
        bucket = parse_us_bucket(label)
        if not bucket:
            continue
        lo, hi, unit = bucket
        rows.append(
            {
                "token_id": mkt["slug"],
                "event_slug": event.get("slug", ""),
                "city": city,
                "target_date": target_date,
                "question": f"{city} {target_date}: {label}",
                "outcome_prices": json.loads(mkt.get("outcomePrices") or "[]"),
                "end_ts": end_ts,
                "closed": bool(mkt.get("closed")) or event_closed,
                "bucket_lo": lo,
                "bucket_hi": hi,
                "unit": unit,
            }
        )
    return rows


def _parse_resolution(market: dict) -> int | None:
    """Outcome (1/0) for a bucket market, or None if not yet resolved.

    Mirrors gamma's pattern: only a *closed* market with a decisive Yes price
    resolves. UNVERIFIED against a genuinely settled US market — as of
    2026-06-21 no temperature market had formally closed (T+1 markets still
    show closed=False and /settlement 404s), so confirm this once one settles.
    """
    if not isinstance(market, dict) or not market.get("closed"):
        return None
    try:
        prices = json.loads(market.get("outcomePrices") or "[]")
    except (TypeError, ValueError):
        return None
    if not prices:
        return None
    yes = float(prices[0])
    return 1 if yes > 0.9 else 0 if yes < 0.1 else None


# ---------- client ----------

class PolymarketUS:
    """Authenticated Polymarket US client (signing + read-only market data).

    Signs each request per docs.polymarket.us: the message ``{timestamp_ms}
    {METHOD}{path}`` is signed with the Ed25519 secret and sent base64-encoded
    in the X-PM-Signature header. The server tolerates a 30s clock skew, so keep
    the host NTP-synced.
    """

    def __init__(
        self,
        creds: Credentials,
        base_url: str = US_BASE,
        gateway_url: str = US_GATEWAY,
    ):
        self._key_id = creds.key_id
        # The secret is a base64 Ed25519 key; the first 32 bytes are the seed.
        self._signer = ed25519.Ed25519PrivateKey.from_private_bytes(
            base64.b64decode(creds.secret_key)[:32]
        )
        self._base_url = base_url.rstrip("/")
        self._gateway_url = gateway_url.rstrip("/")

    @classmethod
    def from_env(cls, **kwargs) -> "PolymarketUS | None":
        """Build from .env credentials, or None if they are unset."""
        creds = load_credentials()
        return cls(creds, **kwargs) if creds else None

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}{method}{path}"
        signature = base64.b64encode(self._signer.sign(message.encode())).decode()
        return {
            "X-PM-Access-Key": self._key_id,
            "X-PM-Timestamp": timestamp,
            "X-PM-Signature": signature,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, base: str | None = None, params: dict | None = None,
             timeout: float = 20.0) -> httpx.Response:
        base = base or self._base_url
        with httpx.Client(timeout=timeout) as client:
            return client.get(
                f"{base}{path}", params=params, headers=self._auth_headers("GET", path)
            )

    # ----- account (api host) -----

    def get_positions(self) -> dict:
        """Return the authenticated account's portfolio positions."""
        r = self._get("/v1/portfolio/positions")
        r.raise_for_status()
        return r.json()

    def verify(self) -> bool:
        """Confirm the credentials authenticate. True on success, else raises."""
        self.get_positions()
        return True

    # ----- market data (gateway host) -----

    def find_weather_markets(self, cities: list, limit: int = 50) -> list[dict]:
        """Active daily-high temperature markets for the configured cities."""
        try:
            r = self._get(
                "/v1/search",
                base=self._gateway_url,
                params={"query": "highest temperature", "limit": limit},
            )
            r.raise_for_status()
            events = r.json().get("events", [])
        except (httpx.HTTPError, ValueError):
            return []
        alias_to_city = build_alias_map(cities)
        year = datetime.now(timezone.utc).year
        rows: list[dict] = []
        for ev in events:
            rows.extend(_event_to_rows(ev, alias_to_city, year))
        return rows

    def get_order_book(self, token_id: str) -> dict | None:
        """Order book for one bucket market (token_id is the bucket slug)."""
        try:
            r = self._get(f"/v1/markets/{token_id}/book", base=self._gateway_url)
            r.raise_for_status()
            return _normalize_book(r.json())
        except (httpx.HTTPError, ValueError):
            return None

    def get_resolutions(self, rows: list) -> dict[str, int | None]:
        """Resolve outcomes per bucket by polling the single-market endpoint.

        Returns None for any bucket not yet closed/decisive — the engine then
        leaves the position open until it resolves.
        """
        out: dict[str, int | None] = {}
        for tid in {r["token_id"] for r in rows}:
            try:
                r = self._get(f"/v1/market/slug/{tid}", base=self._gateway_url)
                if r.status_code != 200:
                    out[tid] = None
                    continue
                payload = r.json()
                market = payload.get("market", payload) if isinstance(payload, dict) else {}
                out[tid] = _parse_resolution(market)
            except (httpx.HTTPError, ValueError):
                out[tid] = None
        return out

    def find_category_markets(self, categories: list[str], limit: int = 100) -> list[dict]:
        """Active reward-eligible markets in the given categories, normalized.

        Returns rows in the internal reward-market contract; only rows with a
        non-None ``reward`` and not ``closed`` are returned."""
        rows: list[dict] = []
        for cat in categories:
            try:
                r = self._get(
                    "/v1/search",
                    base=self._gateway_url,
                    params={"query": cat, "category": cat, "limit": limit},
                )
                r.raise_for_status()
                payload = r.json()
            except (httpx.HTTPError, ValueError):
                continue
            raw_markets = payload.get("markets") or [
                m for ev in payload.get("events", []) for m in (ev.get("markets") or [])
            ]
            for raw in raw_markets:
                row = _normalize_reward_market(raw)
                if row and row["reward"] is not None and not row["closed"]:
                    rows.append(row)
        return rows

    def get_category_resolutions(self, token_ids: list[str]) -> dict[str, int | None]:
        """Resolve outcomes for category markets by slug. None if unresolved.

        Reuses the same single-market endpoint + decisive-price rule as
        get_resolutions, but keyed off a flat token_id list."""
        out: dict[str, int | None] = {}
        for tid in set(token_ids):
            try:
                r = self._get(f"/v1/market/slug/{tid}", base=self._gateway_url)
                if r.status_code != 200:
                    out[tid] = None
                    continue
                payload = r.json()
                market = payload.get("market", payload) if isinstance(payload, dict) else {}
                out[tid] = _parse_resolution(market)
            except (httpx.HTTPError, ValueError):
                out[tid] = None
        return out
