"""Gamma API client — market discovery (read-only, no auth).

Used in phase 1 to find active weather/temperature markets and their
CLOB token IDs. https://gamma-api.polymarket.com
"""

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"


def find_weather_markets(tags: list[str]) -> list[dict]:
    """Return active markets matching the given tags.

    TODO(phase 1): paginate /markets, filter by tag/closed/liquidity,
    return [{question, condition_id, token_ids, end_date, ...}].
    Also resolve open question #1 here: confirm whether the liquid
    weather books live on the international CLOB or Polymarket US.
    """
    raise NotImplementedError
