"""det_gauss_v1: bias-corrected deterministic forecast with a Gaussian error.

The backtestable model. Open-Meteo archives deterministic GFS and ECMWF runs at
fixed lead offsets (Previous Runs API) but not ensembles, so uncertainty comes
from the historical forecast error instead of ensemble spread:

    high ~ Normal(mean(GFS, ECMWF) + bias[station, lead], sigma[station, lead])

bias and sigma are fit on the training window only (see docs/PROTOCOL.md) and
then frozen, so test-window scores are out of sample.
"""
import statistics
from dataclasses import dataclass

from weather_vs_market.model.buckets import bucket_probability

MODEL = "det_gauss_v1"
MODELS = ("gfs_seamless", "ecmwf_ifs025")
MIN_SIGMA = 0.75   # °F; guards against a degenerate fit on a tiny or quantized sample


@dataclass(frozen=True)
class Sample:
    station: str
    lead_days: int
    forecast: float     # mean of the deterministic models' daily max, °F
    observed: float     # official daily high, °F


@dataclass(frozen=True)
class Params:
    bias: float
    sigma: float
    n: int


def mean_forecast(by_model: dict[str, float]) -> float | None:
    """Equal-weight mean of all models; None unless every model is present."""
    if any(m not in by_model for m in MODELS):
        return None
    return sum(by_model[m] for m in MODELS) / len(MODELS)


def fit(samples: list[Sample], min_samples: int = 60) -> dict[tuple[str, int], Params]:
    groups: dict[tuple[str, int], list[float]] = {}
    for s in samples:
        groups.setdefault((s.station, s.lead_days), []).append(s.observed - s.forecast)
    out = {}
    for key, resid in groups.items():
        if len(resid) < min_samples:
            continue
        out[key] = Params(bias=statistics.fmean(resid),
                          sigma=max(statistics.stdev(resid), MIN_SIGMA), n=len(resid))
    return out


def ladder_probs(forecast: float, params: Params,
                 ladder: list[tuple[float | None, float | None]]) -> list[float]:
    mean = forecast + params.bias
    return [bucket_probability([mean], lo, hi, sigma=params.sigma) for lo, hi in ladder]


def params_to_json(params: dict[tuple[str, int], Params]) -> list[dict]:
    return [{"station": st, "lead_days": lead, "bias": round(p.bias, 4),
             "sigma": round(p.sigma, 4), "n": p.n}
            for (st, lead), p in sorted(params.items())]


def params_from_json(rows: list[dict]) -> dict[tuple[str, int], Params]:
    return {(r["station"], r["lead_days"]): Params(r["bias"], r["sigma"], r["n"]) for r in rows}
