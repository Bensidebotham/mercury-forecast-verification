"""Temperature-bucket probability model.

forecast members + live observations -> fair probability per bucket.

Buckets are inclusive integer ranges in reported units (the CLI/official
report rounds to whole degrees), so bucket (82, 83) wins iff the reported
high is 82 or 83. A continuous temperature T maps to it when
81.5 <= T < 83.5 — hence the +/-0.5 in the integration bounds.
"""

import math
import re

_BETWEEN = re.compile(r"between (\d+)-(\d+)\s*°([FC])")
_OR_HIGHER = re.compile(r"be (\d+)\s*°([FC]) or (?:higher|above)")
_OR_BELOW = re.compile(r"be (\d+)\s*°([FC]) or (?:below|lower)")
_EXACT = re.compile(r"be (\d+)\s*°([FC]) on")


def parse_bucket(question: str) -> tuple[float | None, float | None, str] | None:
    """Parse (lo, hi, unit) from a market question. None bound = open end."""
    if m := _BETWEEN.search(question):
        return float(m.group(1)), float(m.group(2)), m.group(3)
    if m := _OR_HIGHER.search(question):
        return float(m.group(1)), None, m.group(2)
    if m := _OR_BELOW.search(question):
        return None, float(m.group(1)), m.group(2)
    if m := _EXACT.search(question):
        v = float(m.group(1))
        return v, v, m.group(2)
    return None


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bucket_probability(
    members: list[float],
    lo: float | None,
    hi: float | None,
    sigma: float = 1.5,
    obs_max: float | None = None,
    locked: bool = False,
    locked_sigma: float = 0.5,
) -> float:
    """P(reported high lands in [lo, hi]) under a kernel mixture.

    Each ensemble member contributes a Gaussian kernel (width sigma).
    obs_max truncates: the final max is max(T_forecast, obs_max), i.e.
    all forecast mass below the observed floor collapses into a point
    mass AT obs_max — buckets entirely below it get exactly 0. When the
    day is locked (past the afternoon peak), the distribution collapses
    to obs_max with a small residual sigma for reporting noise.
    """
    if locked and obs_max is not None:
        members, sigma, obs_max = [obs_max], locked_sigma, None
    if not members:
        return 0.0

    a = lo - 0.5 if lo is not None else -math.inf
    b = hi + 0.5 if hi is not None else math.inf

    def mass(low: float, high: float) -> float:
        """P(T_forecast in [low, high)) under the kernel mixture."""
        total = 0.0
        for m in members:
            upper = _norm_cdf((high - m) / sigma) if high != math.inf else 1.0
            lower = _norm_cdf((low - m) / sigma) if low != -math.inf else 0.0
            total += upper - lower
        return total / len(members)

    if obs_max is None:
        return mass(a, b)
    if b <= obs_max:
        return 0.0  # bucket is entirely below the observed floor — dead
    point = mass(-math.inf, obs_max) if a <= obs_max else 0.0
    return point + mass(max(a, obs_max), b)


def ladder_probabilities(
    members: list[float],
    buckets: list[tuple[float | None, float | None]],
    sigma: float = 1.5,
    obs_max: float | None = None,
    locked: bool = False,
    locked_sigma: float = 0.5,
) -> list[float]:
    """Probabilities for a full bucket ladder, normalized to sum to 1."""
    probs = [
        bucket_probability(members, lo, hi, sigma, obs_max, locked, locked_sigma)
        for lo, hi in buckets
    ]
    s = sum(probs)
    return [p / s for p in probs] if s > 0 else probs


def bias_correction(station: str) -> float:
    """Historical model-vs-observation bias. 0.0 until the calibration
    loop has enough logged forecast/outcome pairs to estimate it."""
    return 0.0
