from polybot.clients.us import (
    PolymarketUS,
    _normalize_incentivized_market,
    _parse_program,
)


# Real /v1/incentives timePeriod shape (confirmed live).
TP = {
    "programId": "cod_ml_live",
    "programType": "liquidityProgram",
    "start": "2026-05-31T00:00:00Z",
    "end": "",
    "rewardPool": 2000,
    "status": "active",
    "discountFactor": 0.3,
    "targetSize": 15000,
    "period": "live",
    "createdAt": "2026-05-30T00:00:00Z",
}

# Real /v1/market/slug/{slug} market-object shape.
DETAIL = {
    "slug": "aec-cod-c9ny-bos-2026-05-31",
    "category": "sports",
    "title": "C9NY vs BOS",
    "question": "Who wins?",
    "endDate": "2026-05-31T20:00:00Z",
    "closed": False,
    "orderPriceMinTickSize": 0.001,
    "outcomePrices": "[0.5, 0.5]",
}


def test_parse_program_extracts_fields():
    p = _parse_program(TP)
    assert p == {
        "pool_usd": 2000.0,
        "discount": 0.3,
        "target_size": 15000.0,
        "period": "live",
        "program_id": "cod_ml_live",
    }


def test_parse_program_none_when_required_field_missing():
    bad = {k: v for k, v in TP.items() if k != "rewardPool"}
    assert _parse_program(bad) is None


def test_normalize_incentivized_market_shape():
    reward = _parse_program(TP)
    row = _normalize_incentivized_market(DETAIL, reward)
    assert row["token_id"] == "aec-cod-c9ny-bos-2026-05-31"
    assert row["event_slug"] == ""
    assert row["category"] == "sports"
    assert row["question"] == "C9NY vs BOS"
    assert row["end_ts"] is not None
    assert row["closed"] is False
    assert row["tick_size"] == 0.001
    assert row["reward"] is reward


def test_normalize_incentivized_market_tick_default():
    detail = {k: v for k, v in DETAIL.items() if k != "orderPriceMinTickSize"}
    row = _normalize_incentivized_market(detail, {})
    assert row["tick_size"] == 0.01


def test_normalize_incentivized_market_none_without_slug():
    assert _normalize_incentivized_market({"category": "sports"}, {}) is None


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _client_with_incentives(payload):
    client = PolymarketUS.__new__(PolymarketUS)
    client._base_url = "https://api.polymarket.us"
    client._gateway_url = "https://gateway.polymarket.us"
    client._get = lambda path, base=None, **kw: _FakeResponse(payload)
    return client


def test_get_incentive_programs_filters_and_picks_richest():
    payload = {
        "programs": [
            # Active market with two active liquidity periods -> keep richer (5000).
            {
                "marketSlug": "rich-market",
                "timePeriods": [
                    {**TP, "rewardPool": 2000},
                    {**TP, "rewardPool": 5000, "programId": "big"},
                ],
            },
            # Only an inactive liquidity period -> dropped.
            {
                "marketSlug": "inactive-market",
                "timePeriods": [{**TP, "status": "ended"}],
            },
            # Active but wrong program type -> dropped.
            {
                "marketSlug": "trade-market",
                "timePeriods": [{**TP, "programType": "tradingProgram"}],
            },
            # Missing slug -> skipped.
            {"timePeriods": [TP]},
        ]
    }
    out = _client_with_incentives(payload).get_incentive_programs()
    assert set(out) == {"rich-market"}
    assert out["rich-market"]["pool_usd"] == 5000.0
    assert out["rich-market"]["program_id"] == "big"


def test_get_incentive_programs_empty_on_no_programs():
    assert _client_with_incentives({}).get_incentive_programs() == {}
