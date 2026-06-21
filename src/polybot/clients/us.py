"""Polymarket US client — authenticated access to api.polymarket.us.

Unlike clob.py/gamma.py (public international read-only endpoints used for
paper-trading data), this targets the CFTC-regulated Polymarket US API, which
authenticates every request with an Ed25519 signature over the credentials
issued at polymarket.us/developer.

Scope is intentionally auth + read-only verification for now: no order
placement until paper results justify a live pilot. Market-data parity with
gamma.py/clob.py is added when the live pilot actually begins.
"""

import base64
import time

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519

from polybot.config import Credentials, load_credentials

US_BASE = "https://api.polymarket.us"


class PolymarketUS:
    """Authenticated Polymarket US client.

    Signs each request per docs.polymarket.us: the message ``{timestamp_ms}
    {METHOD}{path}`` is signed with the Ed25519 secret and sent base64-encoded
    in the X-PM-Signature header. The server tolerates a 30s clock skew, so keep
    the host NTP-synced.
    """

    def __init__(self, creds: Credentials, base_url: str = US_BASE):
        self._key_id = creds.key_id
        # The secret is a base64 Ed25519 key; the first 32 bytes are the seed.
        self._signer = ed25519.Ed25519PrivateKey.from_private_bytes(
            base64.b64decode(creds.secret_key)[:32]
        )
        self._base_url = base_url.rstrip("/")

    @classmethod
    def from_env(cls, base_url: str = US_BASE) -> "PolymarketUS | None":
        """Build from .env credentials, or None if they are unset."""
        creds = load_credentials()
        return cls(creds, base_url=base_url) if creds else None

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

    def _get(self, path: str, timeout: float = 15.0) -> dict:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(
                f"{self._base_url}{path}", headers=self._auth_headers("GET", path)
            )
            resp.raise_for_status()
            return resp.json()

    def get_positions(self) -> dict:
        """Return the authenticated account's portfolio positions."""
        return self._get("/v1/portfolio/positions")

    def verify(self) -> bool:
        """Confirm the credentials authenticate. True on success, else raises."""
        self.get_positions()
        return True
