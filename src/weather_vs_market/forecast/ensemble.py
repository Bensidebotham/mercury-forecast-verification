"""Ensemble members via open-meteo (free, no key): the live uncertainty signal.

GFS (31 members) + ECMWF IFS (51 members) give a distribution over the
daily high, not just a point estimate. Open-Meteo keeps no archive of past
ensemble runs, so this model can only be scored forward, on live snapshots.
"""

import httpx

from weather_vs_market import USER_AGENT

ENSEMBLE_BASE = "https://ensemble-api.open-meteo.com/v1/ensemble"
MODELS = "gfs025,ecmwf_ifs025"


def get_ensemble_members(
    lat: float, lon: float, tz: str, target_date: str, unit: str = "F"
) -> list[float]:
    """Predicted daily-high temps for target_date, one per ensemble member.

    Returns [] on error or if the horizon doesn't cover the date.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "models": MODELS,
        "timezone": tz,
        "forecast_days": 7,
    }
    if unit.upper() == "F":
        params["temperature_unit"] = "fahrenheit"
    try:
        with httpx.Client(headers=USER_AGENT, timeout=30) as client:
            resp = client.get(ENSEMBLE_BASE, params=params)
            resp.raise_for_status()
            payloads = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    # one payload per model when multiple models requested; normalize to list
    if isinstance(payloads, dict):
        payloads = [payloads]

    members: list[float] = []
    for payload in payloads:
        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        day_idx = [i for i, t in enumerate(times) if t.startswith(target_date)]
        if not day_idx:
            continue
        for key, series in hourly.items():
            if not key.startswith("temperature_2m"):
                continue
            vals = [series[i] for i in day_idx if series[i] is not None]
            if vals:
                members.append(max(vals))
    return members
