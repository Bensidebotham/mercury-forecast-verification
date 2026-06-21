# Polymarket US auth plumbing — design

**Date:** 2026-06-20
**Status:** Approved (scope: auth + verify only)

## Goal

Wire the verified Polymarket US Ed25519 authentication into the codebase using
the canonical env vars `POLYMARKET_KEY_ID` and `POLYMARKET_SECRET_KEY`, replacing
the throwaway verification script with a declared, tested module.

## Context

- Platform is **Polymarket US** (`https://api.polymarket.us`), CFTC-regulated,
  2-key Ed25519 auth — not classic wallet-based Polymarket, not Kalshi.
- Credentials live in `.env` (gitignored), loaded by `config.py` via
  `load_dotenv(ROOT / ".env")`.
- Auth was manually verified working: `GET /v1/portfolio/positions` returned 200.
- `gamma.py`/`clob.py` are public read-only (paper data). `gamma.py` already
  anticipates a `clients/us.py` for the live pilot.
- Nothing in `src/` currently reads any credentials, so there are no stale
  references to migrate — this is net-new plumbing.

## Non-goals

- No order placement (repo is paper-only until results justify a live pilot).
- No market-data parity with gamma/clob yet (deferred to live-pilot work, YAGNI).

## Design

### 1. `config.py` — credentials accessor (separate from `Settings`)

`Settings` holds non-secret YAML config; secrets stay out of it. Add:

```python
class Credentials(BaseModel):
    key_id: str
    secret_key: str  # base64-encoded Ed25519 private key

def load_credentials() -> Credentials | None:
    load_dotenv(ROOT / ".env")
    key_id = os.getenv("POLYMARKET_KEY_ID")
    secret = os.getenv("POLYMARKET_SECRET_KEY")
    if not key_id or not secret:
        return None
    return Credentials(key_id=key_id, secret_key=secret)
```

Returns `None` when unset so paper mode runs credential-free.

### 2. `clients/us.py` — authenticated Polymarket US client

- `US_BASE = "https://api.polymarket.us"`
- `PolymarketUS(creds: Credentials)`:
  - Loads the signing key once: `ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(creds.secret_key)[:32])`.
  - `_auth_headers(method, path)`: timestamp ms, message `f"{ts}{method}{path}"`,
    `X-PM-Access-Key` / `X-PM-Timestamp` / `X-PM-Signature` (base64 sig),
    `Content-Type: application/json`.
  - `get_positions() -> dict`: `GET /v1/portfolio/positions`, raises on non-2xx.
  - `verify() -> bool`: calls `get_positions()`, returns `True` on success.
- `from_env() -> PolymarketUS | None` classmethod: builds from `load_credentials()`.

### 3. `tests/test_us_auth.py` — offline signing test

No network, no real secret. Generate an ephemeral Ed25519 keypair, run it through
the same header-building code, and cryptographically verify the signature over
`f"{ts}{method}{path}"` plus assert header names/shape. Locks signing logic in CI.

### 4. `pyproject.toml`

Add `cryptography` to `dependencies` (currently installed ad-hoc).

## Verification

- `pytest tests/test_us_auth.py` passes offline.
- Existing test suite still green.
- Manual `PolymarketUS.from_env().verify()` returns `True` against live API
  (already confirmed once via the throwaway script).
