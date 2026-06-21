"""Market-data provider selection.

The PaperEngine consumes three operations — find_weather_markets,
get_order_book, get_resolutions — from whichever venue is configured. Both
providers return identical shapes so the engine is venue-agnostic.
"""

from polybot.clients import clob, gamma
from polybot.clients.us import PolymarketUS


class InternationalData:
    """Adapter over the public gamma/clob endpoints (no auth)."""

    def find_weather_markets(self, cities: list, limit: int = 50) -> list[dict]:
        return gamma.find_weather_markets(cities, limit)

    def get_order_book(self, token_id: str) -> dict | None:
        return clob.get_order_book(token_id)

    def get_resolutions(self, rows: list) -> dict[str, int | None]:
        return gamma.get_event_resolutions([r["event_slug"] for r in rows])


def build_data_provider(settings):
    """Return the market-data provider for the configured data_source."""
    if getattr(settings, "data_source", "us") == "us":
        client = PolymarketUS.from_env()
        if client is None:
            raise RuntimeError(
                "data_source='us' requires POLYMARKET_KEY_ID and "
                "POLYMARKET_SECRET_KEY in .env"
            )
        return client
    return InternationalData()
