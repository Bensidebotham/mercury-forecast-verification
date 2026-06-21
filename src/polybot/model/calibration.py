"""Online calibration: learn the model's true reliability from outcomes.

The raw bucket model is systematically overconfident below ~0.3 (measured:
it assigns 5-25% to buckets that win ~0% of the time). This maps each raw
model probability through the empirical win-rate of settled trades, so the
strategy acts on calibrated probabilities instead of optimistic ones.

Isotonic (monotone, pooled-adjacent-violators) fit on settled BUY fills:
non-decreasing, so a higher model prob never maps to a lower corrected one.
Falls back to identity until enough settlements exist.
"""

import json
import sqlite3
from pathlib import Path

MIN_SAMPLES = 40  # below this, not enough settled data to trust the fit


def _isotonic(points: list[tuple[float, float, int]]) -> list[tuple[float, float]]:
    """Pool-adjacent-violators. points = [(x, y, weight)] sorted by x.
    Returns [(x, y_fitted)] with non-decreasing y."""
    blocks = [[x, y, w] for x, y, w in points]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][1] > blocks[i + 1][1]:  # violation: merge
            x0, y0, w0 = blocks[i]
            x1, y1, w1 = blocks[i + 1]
            merged = [x1, (y0 * w0 + y1 * w1) / (w0 + w1), w0 + w1]
            blocks[i : i + 2] = [merged]
            if i > 0:
                i -= 1
        else:
            i += 1
    return [(b[0], b[1]) for b in blocks]


def fit_calibration(conn: sqlite3.Connection, bins: int = 10) -> list[tuple[float, float]] | None:
    """Return a monotone [(model_prob, corrected_prob)] mapping, or None
    if too few settled samples. Built from settled BUY fills."""
    rows = conn.execute(
        """SELECT f.model_prob AS p, s.outcome AS o
           FROM paper_fills f JOIN settlements s ON s.token_id = f.token_id
           WHERE f.side='BUY' AND f.model_prob IS NOT NULL"""
    ).fetchall()
    if len(rows) < MIN_SAMPLES:
        return None
    buckets: dict[int, list[int]] = {}
    for r in rows:
        b = min(int(r["p"] * bins), bins - 1)
        buckets.setdefault(b, []).append(r["o"])
    points = []
    for b in sorted(buckets):
        outs = buckets[b]
        x = (b + 0.5) / bins
        points.append((x, sum(outs) / len(outs), len(outs)))
    return _isotonic(points)


def save_calibration(mapping: list[tuple[float, float]] | None, path: str) -> None:
    """Persist the fitted curve so it survives a database reset."""
    if not mapping:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(mapping, f)


def load_calibration(path: str) -> list[tuple[float, float]] | None:
    """Load a previously persisted curve, or None if absent."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return [tuple(pair) for pair in json.load(open(p))]
    except (ValueError, OSError):
        return None


def apply_calibration(prob: float, mapping: list[tuple[float, float]] | None) -> float:
    """Map a raw model prob through the fitted curve (linear interp).
    Identity when no mapping yet."""
    if not mapping:
        return prob
    if prob <= mapping[0][0]:
        # extrapolate below first knot toward 0, scaled by first knot
        x0, y0 = mapping[0]
        return prob / x0 * y0 if x0 > 0 else 0.0
    if prob >= mapping[-1][0]:
        return mapping[-1][1]
    for (x0, y0), (x1, y1) in zip(mapping, mapping[1:]):
        if x0 <= prob <= x1:
            t = (prob - x0) / (x1 - x0) if x1 > x0 else 0.0
            return y0 + t * (y1 - y0)
    return prob
