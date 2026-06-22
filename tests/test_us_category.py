from polybot.clients.us import _normalize_reward_market, _parse_reward_params


# Synthetic payload in the shape observed by the probe in Step 2.
# (If the probe revealed different key names, update RAW here AND the parser to match.)
RAW = {
    "slug": "fed-cuts-in-july-2026",
    "eventSlug": "fed-july-2026",
    "category": "Macro",
    "title": "Will the Fed cut rates in July 2026?",
    "endDate": "2026-07-31T20:00:00Z",
    "closed": False,
    "rewards": {
        "dailyPoolUsd": 1000.0,
        "discountFactor": 0.30,
        "targetSize": 20000,
        "maxSpread": 0.03,
        "minSize": 50,
    },
}


def test_parse_reward_params_extracts_fields():
    p = _parse_reward_params(RAW)
    assert p == {
        "pool_usd": 1000.0,
        "discount": 0.30,
        "target_size": 20000.0,
        "max_spread": 0.03,
        "min_size": 50.0,
    }


def test_parse_reward_params_none_when_absent():
    assert _parse_reward_params({"slug": "x"}) is None


def test_normalize_reward_market_shape():
    row = _normalize_reward_market(RAW)
    assert row["token_id"] == "fed-cuts-in-july-2026"
    assert row["category"] == "Macro"
    assert row["closed"] is False
    assert row["end_ts"] is not None
    assert row["reward"]["target_size"] == 20000.0
