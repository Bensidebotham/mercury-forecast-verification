"""NWS point forecasts (free, no key, https://api.weather.gov).

Markets settle against each city's NWS Daily Climate Report (CLI),
so forecasts and observations are anchored to the same stations the
exchange uses (KNYC, KSFO, KMIA, KMDW, KLAX).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

NWS_BASE = "https://api.weather.gov"
UA = {"User-Agent": "polybot/0.1 (bensidebotham89@gmail.com)"}


def get_hourly_daily_max(lat: float, lon: float, tz: str, target_date: str) -> float | None:
    """NWS hourly forecast -> predicted daily max (°F) for target_date (local).

    Returns None if the forecast horizon doesn't cover the date.
    """
    zone = ZoneInfo(tz)
    try:
        with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as client:
            point = client.get(f"{NWS_BASE}/points/{lat:.4f},{lon:.4f}")
            point.raise_for_status()
            hourly_url = point.json()["properties"]["forecastHourly"]
            fc = client.get(hourly_url)
            fc.raise_for_status()
            periods = fc.json()["properties"]["periods"]
    except (httpx.HTTPError, KeyError, ValueError):
        return None

    temps = []
    for p in periods:
        ts = datetime.fromisoformat(p["startTime"]).astimezone(zone)
        if ts.strftime("%Y-%m-%d") == target_date and p.get("temperatureUnit") == "F":
            temps.append(float(p["temperature"]))
    return max(temps) if temps else None
