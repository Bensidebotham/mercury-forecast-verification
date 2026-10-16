"""weather-vs-market: score weather-model probabilities against prediction markets."""

__version__ = "0.3.0"

# NWS asks API clients to identify themselves with a contact; the repo URL serves.
USER_AGENT = {"User-Agent": f"weather-vs-market/{__version__} (github.com/Bensidebotham/weather-vs-market)"}
