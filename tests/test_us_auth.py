"""Offline tests for Polymarket US request signing — no network, no real keys."""

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from polybot.clients.us import PolymarketUS
from polybot.config import Credentials, load_credentials


def _secret_b64(key: ed25519.Ed25519PrivateKey, *, with_pubkey: bool) -> str:
    """Encode an Ed25519 private key the way the portal does.

    32-byte form is the seed alone; 64-byte form is seed + public key (what the
    real Polymarket US secret uses — 88 base64 chars).
    """
    seed = key.private_bytes_raw()
    raw = seed + key.public_key().public_bytes_raw() if with_pubkey else seed
    return base64.b64encode(raw).decode()


@pytest.mark.parametrize("with_pubkey", [False, True], ids=["32-byte", "64-byte"])
def test_auth_headers_signature_verifies(with_pubkey):
    key = ed25519.Ed25519PrivateKey.generate()
    creds = Credentials(key_id="kid-123", secret_key=_secret_b64(key, with_pubkey=with_pubkey))
    client = PolymarketUS(creds)

    method, path = "GET", "/v1/portfolio/positions"
    headers = client._auth_headers(method, path)

    assert headers["X-PM-Access-Key"] == "kid-123"
    assert set(headers) == {
        "X-PM-Access-Key",
        "X-PM-Timestamp",
        "X-PM-Signature",
        "Content-Type",
    }
    assert headers["X-PM-Timestamp"].isdigit()

    # The signature must validate against the public key over "{ts}{method}{path}".
    message = f"{headers['X-PM-Timestamp']}{method}{path}".encode()
    signature = base64.b64decode(headers["X-PM-Signature"])
    key.public_key().verify(signature, message)  # raises InvalidSignature on mismatch


def test_signature_is_path_specific():
    key = ed25519.Ed25519PrivateKey.generate()
    client = PolymarketUS(Credentials(key_id="k", secret_key=_secret_b64(key, with_pubkey=True)))

    headers = client._auth_headers("GET", "/v1/portfolio/positions")
    wrong = f"{headers['X-PM-Timestamp']}GET/v1/other".encode()
    with pytest.raises(Exception):
        key.public_key().verify(base64.b64decode(headers["X-PM-Signature"]), wrong)


def test_load_credentials_none_when_unset(monkeypatch):
    monkeypatch.delenv("POLYMARKET_KEY_ID", raising=False)
    monkeypatch.delenv("POLYMARKET_SECRET_KEY", raising=False)
    # Point dotenv at a dir with no .env so nothing is loaded back in.
    monkeypatch.setattr("polybot.config.ROOT", __import__("pathlib").Path("/nonexistent"))
    assert load_credentials() is None


def test_from_env_none_when_unset(monkeypatch):
    monkeypatch.setattr("polybot.clients.us.load_credentials", lambda: None)
    assert PolymarketUS.from_env() is None
