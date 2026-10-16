"""Fit det_gauss_v1 on the training window and freeze the parameters.

Truth is the NWS CLI daily high at each settlement station (via IEM); forecasts
are Open-Meteo Previous Runs daily maxima at each lead offset. Only target dates
inside the training window are read, so nothing from the test window can leak
into the parameters.
"""
import json
import logging
import statistics
import time
from datetime import date

from weather_vs_market.config import ROOT, Settings
from weather_vs_market.forecast import iem, previous_runs
from weather_vs_market.model import det_gauss as D

log = logging.getLogger("wvm.fit")

TRAIN = ("2024-01-01", "2025-06-30")
PARAMS_FILE = ROOT / "config" / "det_gauss_v1.params.json"
LOCKED_FILE = ROOT / "config" / "locked_obs.params.json"
MIN_LOCKED_SIGMA = 0.5   # °F


def settlement_stations(settings: Settings) -> list[str]:
    ids = {v.station for v in settings.venues.kalshi} | {v.station for v in settings.venues.polymarket}
    return sorted(ids)


def samples_for_station(settings: Settings, station_id: str, start: str, end: str,
                        leads: tuple[int, ...]) -> list[D.Sample]:
    st = settings.station(station_id)
    highs: dict[str, int] = {}
    for year in range(int(start[:4]), int(end[:4]) + 1):
        highs.update(iem.fetch_cli_highs(station_id, year, tz=st.tz))
    maxima = previous_runs.fetch_daily_max_by_lead(st.lat, st.lon, st.tz, start, end, leads=leads,
                                                   models=D.MODELS)
    by_day_lead: dict[tuple[str, int], dict[str, float]] = {}
    for (day, model, lead), value in maxima.items():
        by_day_lead.setdefault((day, lead), {})[model] = value
    out = []
    for (day, lead), by_model in sorted(by_day_lead.items()):
        if not start <= day <= end or day not in highs:
            continue
        fc = D.mean_forecast(by_model)
        if fc is not None:
            out.append(D.Sample(station_id, lead, fc, float(highs[day])))
    return out


def run_fit(settings: Settings) -> dict:
    leads = tuple(sorted({lp.previous_run_days for lp in settings.evaluation.lead_points}))
    samples: list[D.Sample] = []
    for station_id in settlement_stations(settings):
        s = samples_for_station(settings, station_id, *TRAIN, leads=leads)
        log.info("%s: %d training samples", station_id, len(s))
        samples += s
    params = D.fit(samples)
    doc = {"model": D.MODEL, "train_window": list(TRAIN), "fit_at": date.today().isoformat(),
           "fit_ts": time.time(), "params": D.params_to_json(params)}
    PARAMS_FILE.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def load_params() -> dict[tuple[str, int], D.Params]:
    return D.params_from_json(json.loads(PARAMS_FILE.read_text())["params"])


# Locked-day calibration for the live ensemble model. Hourly METAR misses peaks
# between reports, so the official CLI high usually sits above the hourly max
# (KMIA 2026-10-09: METAR 89, CLI 90). Fit CLI high - hourly max per station on
# the training window, and use it once the day is locked.

def locked_residuals(temps: list[tuple[str, float]], highs: dict[str, int]) -> list[float]:
    daily: dict[str, float] = {}
    for ts, t in temps:
        d = ts[:10]
        daily[d] = max(daily.get(d, t), t)
    return [highs[d] - m for d, m in sorted(daily.items()) if d in highs]


def locked_params(residuals: list[float]) -> dict:
    return {"bias": round(statistics.fmean(residuals), 4),
            "sigma": round(max(statistics.stdev(residuals), MIN_LOCKED_SIGMA), 4), "n": len(residuals)}


def run_fit_locked(settings: Settings) -> dict:
    out = {}
    for station_id in settlement_stations(settings):
        st = settings.station(station_id)
        highs: dict[str, int] = {}
        for year in range(int(TRAIN[0][:4]), int(TRAIN[1][:4]) + 1):
            highs.update(iem.fetch_cli_highs(station_id, year, tz=st.tz))
        resid = locked_residuals(iem.fetch_hourly_temps(station_id, *TRAIN, tz=st.tz), highs)
        out[station_id] = locked_params(resid)
        log.info("%s locked-day residual: %s", station_id, out[station_id])
    doc = {"train_window": list(TRAIN), "fit_at": date.today().isoformat(), "stations": out}
    LOCKED_FILE.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def load_locked_params() -> dict[str, dict]:
    return json.loads(LOCKED_FILE.read_text())["stations"] if LOCKED_FILE.exists() else {}
