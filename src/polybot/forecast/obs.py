"""Live station observations — the lock-in signal.

The day's high is physically monotone: once the station has observed
T, the settled max cannot be below T. Buckets below the running max
are dead; quotes that haven't repriced are free edge. After the
afternoon peak (lock_hour_local), the max is effectively final.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

NWS_BASE = "https://api.weather.gov"
UA = {"User-Agent": "polybot/0.1 (bensidebotham89@gmail.com)"}


def get_running_max(station: str, tz: str, target_date: str, unit: str = "F") -> float | None:
    """Max observed temperature at the station so far on target_date (local).

    Returns None if no observations are available (or the date is in
    the future for that timezone).
    """
    zone = ZoneInfo(tz)
    day_start = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=zone)
    start_utc = (day_start - timedelta(hours=1)).isoformat()
    try:
        with httpx.Client(headers=UA, timeout=20) as client:
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


def is_plateaued(
    history: list[tuple[float, float]],
    tz: str,
    target_date: str,
    earliest_lock_hour: int,
    plateau_hours: float,
    now_ts: float,
) -> bool:
    """True if the daily high looks physically locked in: it's past
    earliest_lock_hour local and the observed max hasn't risen during the
    last `plateau_hours` (the recent window's peak doesn't exceed what was
    already seen before it). history = [(ts, obs_max)] for this city/date.

    Detects the mid-afternoon lock window without waiting for a blind
    evening cutoff — but stays conservative (needs a full window of data
    and a real plateau) to avoid calling the high early on a slow climb.
    """
    zone = ZoneInfo(tz)
    # Derive "now" entirely from now_ts so the function is deterministic and
    # replayable (don't mix in wall-clock datetime.now()).
    now_local = datetime.fromtimestamp(now_ts, zone)
    today = now_local.strftime("%Y-%m-%d")
    if target_date < today:
        return True
    if target_date > today:
        return False
    if now_local.hour < earliest_lock_hour:
        return False
    cutoff = now_ts - plateau_hours * 3600
    before = [m for ts, m in history if ts < cutoff]
    recent = [m for ts, m in history if ts >= cutoff]
    if not before or not recent:
        return False  # not enough history to judge a plateau yet
    # Plateaued if nothing in the recent window exceeded the prior peak.
    return max(recent) <= max(before) + 0.1
