"""Offline tests for Polymarket US market-data normalization (real fixtures)."""

import types

import pytest

from polybot.clients import provider
from polybot.clients.provider import InternationalData, build_data_provider
from polybot.clients.us import _event_to_rows, _normalize_book, _parse_resolution
from polybot.model.buckets import parse_us_bucket


def test_parse_us_bucket_forms():
    assert parse_us_bucket("64 or below") == (None, 64.0, "F")
    assert parse_us_bucket("73 or above") == (73.0, None, "F")
    assert parse_us_bucket("65 to 66") == (65.0, 66.0, "F")
    assert parse_us_bucket("nonsense") is None


# Captured from gateway.polymarket.us /v1/markets/{slug}/book
BOOK_FIXTURE = {
    "marketData": {
        "marketSlug": "tc-temp-sfohigh-2026-06-21-lt65f",
        "bids": [{"px": {"value": "0.0100", "currency": "USD"}, "qty": "20001.8000"}],
        "offers": [
            {"px": {"value": "0.1800", "currency": "USD"}, "qty": "336.0000"},
            {"px": {"value": "0.2900", "currency": "USD"}, "qty": "1010.0000"},
            {"px": {"value": "0.1900", "currency": "USD"}, "qty": "244.2000"},
        ],
    }
}


def test_normalize_book():
    book = _normalize_book(BOOK_FIXTURE)
    assert book["best_bid"] == 0.01
    assert book["best_ask"] == 0.18  # offers sorted ascending
    assert book["bid_depth"] == 20001.8
    assert book["ask_depth"] == 336.0
    assert [a[0] for a in book["asks"]] == [0.18, 0.19, 0.29]


def test_normalize_book_empty():
    assert _normalize_book({}) is None
    empty = _normalize_book({"marketData": {"bids": [], "offers": []}})
    assert empty["best_bid"] is None and empty["bid_depth"] == 0.0


# Captured climate event shape (trimmed)
EVENT_FIXTURE = {
    "slug": "temp-sfohigh-2026-06-21",
    "title": "Highest temperature in San Francisco on June 21?",
    "endDate": "2026-06-21T23:59:00Z",
    "closed": False,
    "markets": [
        {"slug": "tc-temp-sfohigh-2026-06-21-lt65f", "titleShort": "64 or below",
         "outcomePrices": '["0.0100","0.1800"]', "closed": False},
        {"slug": "tc-temp-sfohigh-2026-06-21-gte65lt66f", "titleShort": "65 to 66",
         "outcomePrices": '["0.1000"]', "closed": False},
        {"slug": "tc-temp-sfohigh-2026-06-21-gte73f", "titleShort": "73 or above",
         "outcomePrices": '["0.0500"]', "closed": False},
    ],
}


def test_event_to_rows():
    alias = {"san francisco": "San Francisco"}
    rows = _event_to_rows(EVENT_FIXTURE, alias, 2026)
    assert len(rows) == 3
    first = rows[0]
    assert first["token_id"] == "tc-temp-sfohigh-2026-06-21-lt65f"
    assert first["city"] == "San Francisco"
    assert first["target_date"] == "2026-06-21"
    assert (first["bucket_lo"], first["bucket_hi"], first["unit"]) == (None, 64.0, "F")
    assert first["event_slug"] == "temp-sfohigh-2026-06-21"
    assert rows[1]["bucket_lo"] == 65.0 and rows[1]["bucket_hi"] == 66.0
    assert rows[2]["bucket_lo"] == 73.0 and rows[2]["bucket_hi"] is None


def test_event_to_rows_unconfigured_city_skipped():
    rows = _event_to_rows(EVENT_FIXTURE, {"miami": "Miami"}, 2026)
    assert rows == []


def test_parse_resolution():
    assert _parse_resolution({"closed": False, "outcomePrices": '["0.99"]'}) is None
    assert _parse_resolution({"closed": True, "outcomePrices": '["0.99"]'}) == 1
    assert _parse_resolution({"closed": True, "outcomePrices": '["0.01"]'}) == 0
    assert _parse_resolution({"closed": True, "outcomePrices": '["0.50"]'}) is None
    assert _parse_resolution({"closed": True, "outcomePrices": "[]"}) is None


def test_build_data_provider_international():
    s = types.SimpleNamespace(data_source="international")
    assert isinstance(build_data_provider(s), InternationalData)


def test_build_data_provider_us_requires_creds(monkeypatch):
    monkeypatch.setattr(provider.PolymarketUS, "from_env", staticmethod(lambda **kw: None))
    s = types.SimpleNamespace(data_source="us")
    with pytest.raises(RuntimeError, match="POLYMARKET_KEY_ID"):
        build_data_provider(s)


def test_build_data_provider_us_returns_client(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(provider.PolymarketUS, "from_env", staticmethod(lambda **kw: sentinel))
    s = types.SimpleNamespace(data_source="us")
    assert build_data_provider(s) is sentinel
