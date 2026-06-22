"""Parse Kalshi high-temperature strike labels into bucket bounds.

Returns (lo, hi, unit) with None for an open-ended side, or None if the label
isn't a temperature bucket. Mirrors model/buckets.parse_bucket's contract so the
existing bucket_probability() can score Kalshi markets unchanged.
"""
import re

_RANGE = re.compile(r"(-?\d+(?:\.\d+)?)\s*[-–to]+\s*(-?\d+(?:\.\d+)?)")
_BELOW = re.compile(r"(-?\d+(?:\.\d+)?)\s*°?\s*(?:or below|or lower|and below)", re.I)
_ABOVE = re.compile(r"(-?\d+(?:\.\d+)?)\s*°?\s*(?:or above|or higher|and above)", re.I)

def parse_kalshi_strike(label: str) -> tuple[float | None, float | None, str] | None:
    s = label.strip()
    m = _BELOW.search(s)
    if m:
        return (None, float(m.group(1)), "F")
    m = _ABOVE.search(s)
    if m:
        return (float(m.group(1)), None, "F")
    m = _RANGE.search(s)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (min(lo, hi), max(lo, hi), "F")
    return None
