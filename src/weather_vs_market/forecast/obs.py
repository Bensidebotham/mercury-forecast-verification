"""Live station observations — the lock-in signal.

The day's high is physically monotone: once the station has observed
T, the settled max cannot be below T. Buckets below the running max
can't win. After the afternoon peak (lock_hour_local), the max is effectively final.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from weather_vs_market import USER_AGENT

NWS_BASE = "https://api.weather.gov"


def get_running_max(station: str, tz: str, target_date: str, unit: str = "F") -> float | None:
    """Max observed temperature at the station so far on target_date (local).

    Returns None if no observations are available (or the date is in
    the future for that timezone).
    """
    zone = ZoneInfo(tz)
    day_start = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=zone)
    start_utc = (day_start - timedelta(hours=1)).isoformat()
    try:
        with httpx.Client(headers=USER_AGENT, timeout=20) as client:
            resp = client.get(
                f"{NWS_BASE}/stations/{station}/observations",
                params={"start": start_utc, "limit": 200},
            )
            resp.raise_for_status()
            feats = resp.json().get("features", [])
    except (httpx.HTTPError, ValueError):
        return None

    temps = []
    for f in feats:
        props = f.get("properties", {})
        val_c = (props.get("temperature") or {}).get("value")
        ts_raw = props.get("timestamp")
        if val_c is None or not ts_raw:
            continue
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).astimezone(zone)
        if ts.strftime("%Y-%m-%d") != target_date:
            continue
        temps.append(val_c * 9 / 5 + 32 if unit.upper() == "F" else val_c)
    return max(temps) if temps else None


def is_day_locked(tz: str, target_date: str, lock_hour: int) -> bool:
    """True once local time on target_date has passed lock_hour (or the
    date is already past) — the daily max is then treated as final."""
    zone = ZoneInfo(tz)
    now = datetime.now(zone)
    today = now.strftime("%Y-%m-%d")
    if target_date < today:
        return True
    if target_date > today:
        return False
    return now.hour >= lock_hour

