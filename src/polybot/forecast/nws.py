"""NWS/NDFD point forecasts (free, no key, https://api.weather.gov).

Primary forecast source: hourly temperature forecasts per station.
Markets resolve against station observations, so the station ID in
settings must match each market's resolution source exactly.
"""


def get_hourly_forecast(station: str) -> list[dict]:
    """Return hourly temperature forecast for a station.

    TODO(phase 2): resolve station -> gridpoint, GET /gridpoints/.../hourly,
    return [{ts, temp_f}]. Respect User-Agent requirement.
    """
    raise NotImplementedError
