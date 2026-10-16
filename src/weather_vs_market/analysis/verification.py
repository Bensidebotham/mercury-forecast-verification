"""Score model-implied vs. market-implied probabilities against settled outcomes.

The unit of analysis is the event: one city's daily high on one date, as one
venue's full bucket ladder. Buckets within an event are mutually exclusive and
highly correlated, so counting them as independent samples would overstate the
evidence; scores are computed per event and confidence intervals resample events.

For each event and lead point, every bucket needs a model and a market snapshot
taken at or before the lead time (never after: that would leak information) and
within `tolerance_s` of it. Market mids are normalized across the ladder to
remove the overround; both sides are floored at PROB_FLOOR before log scoring.
"""
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Engine

from weather_vs_market.storage import store

PROB_FLOOR = 0.001


@dataclass(frozen=True)
class LeadPoint:
    """A fixed local clock time relative to the target date, e.g. D-1 12:00."""
    name: str
    day_offset: int
    hour: int

    def timestamp(self, target_date: str, tz: str) -> float:
        d = date.fromisoformat(target_date) + timedelta(days=self.day_offset)
        return datetime(d.year, d.month, d.day, self.hour, tzinfo=ZoneInfo(tz)).timestamp()


def brier(prob: float, outcome: int) -> float:
    return (prob - outcome) ** 2


def log_loss(prob: float, outcome: int, eps: float = 1e-9) -> float:
    p = min(max(prob, eps), 1 - eps)
    return -(outcome * math.log(p) + (1 - outcome) * math.log(1 - p))


def rps(probs: list[float], winner: int) -> float:
    """Ranked probability score over an ordered ladder (0 = perfect)."""
    total = cum_p = cum_o = 0.0
    for i, p in enumerate(probs[:-1]):
        cum_p += p
        cum_o += 1.0 if i == winner else 0.0
        total += (cum_p - cum_o) ** 2
    return total / max(len(probs) - 1, 1)


def _normalize(probs: list[float]) -> list[float]:
    s = sum(probs)
    return [p / s for p in probs] if s > 0 else probs


def _as_of(snaps: list[tuple[float, float]], point_ts: float, tolerance_s: float) -> float | None:
    """Value of the latest snapshot at or before point_ts, if recent enough."""
    best = None
    for ts, v in snaps:
        if ts <= point_ts and (best is None or ts > best[0]):
            best = (ts, v)
    if best is None or point_ts - best[0] > tolerance_s:
        return None
    return best[1]


def _sort_key(m: dict) -> float:
    return m["bucket_lo"] if m["bucket_lo"] is not None else -math.inf


def event_frame(engine: Engine, *, venue: str, model: str, lead_points: list[LeadPoint],
                tz_for_city: dict[str, str], quote_sources: tuple[str, ...] | None = None,
                tolerance_s: float = 2 * 3600) -> list[dict]:
    """One scored row per (event, lead point) with a complete, settled ladder."""
    markets = [m for m in store.read_markets(engine, store.vmarket.c.venue == venue)
               if m["settled"]]
    quotes, preds = defaultdict(list), defaultdict(list)
    for q in store.read_quotes(engine):
        if quote_sources is None or q["source"] in quote_sources:
            quotes[q["market_uid"]].append((q["ts"], q["market_prob"]))
    for p in store.read_preds(engine, store.vpred.c.model == model):
        preds[p["market_uid"]].append((p["ts"], p["model_prob"]))

    events = defaultdict(list)
    for m in markets:
        events[m["event_key"]].append(m)

    frame = []
    for event_key, ladder in events.items():
        ladder.sort(key=_sort_key)
        outcomes = [int(m["outcome"]) for m in ladder]
        if sum(outcomes) != 1:
            continue
        winner = outcomes.index(1)
        first = ladder[0]
        tz = tz_for_city.get(first["city"])
        if tz is None:
            continue
        for lp in lead_points:
            point_ts = lp.timestamp(first["target_date"], tz)
            model_p = [_as_of(preds[m["market_uid"]], point_ts, tolerance_s) for m in ladder]
            market_p = [_as_of(quotes[m["market_uid"]], point_ts, tolerance_s) for m in ladder]
            if None in model_p or None in market_p:
                continue
            model_p, market_p = _normalize(model_p), _normalize(market_p)
            frame.append({
                "venue": venue, "event_key": event_key, "city": first["city"],
                "target_date": first["target_date"], "lead": lp.name,
                "buckets": [[m["bucket_lo"], m["bucket_hi"]] for m in ladder],
                "outcomes": outcomes, "model_probs": model_p, "market_probs": market_p,
                "model_brier": sum(brier(p, o) for p, o in zip(model_p, outcomes, strict=True)),
                "market_brier": sum(brier(p, o) for p, o in zip(market_p, outcomes, strict=True)),
                "model_rps": rps(model_p, winner), "market_rps": rps(market_p, winner),
                "model_logscore": -math.log(max(model_p[winner], PROB_FLOOR)),
                "market_logscore": -math.log(max(market_p[winner], PROB_FLOOR)),
            })
    return frame


_METRICS = ("brier", "rps", "logscore")


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def summarize(events: list[dict], n_boot: int = 2000, seed: int = 0) -> list[dict]:
    """Mean scores per lead point, with a paired event bootstrap on model - market.

    Negative differences mean the model scored better (lower is better for all three).
    """
    rng = random.Random(seed)
    by_lead = defaultdict(list)
    for e in events:
        by_lead[e["lead"]].append(e)
    out = []
    for lead, rows in by_lead.items():
        n = len(rows)
        row = {"lead": lead, "n_events": n}
        diffs = {k: [r[f"model_{k}"] - r[f"market_{k}"] for r in rows] for k in _METRICS}
        boots = {k: [] for k in _METRICS}
        for _ in range(n_boot):
            idx = [rng.randrange(n) for _ in range(n)]
            for k in _METRICS:
                boots[k].append(_mean([diffs[k][i] for i in idx]))
        for k in _METRICS:
            row[f"model_{k}"] = _mean([r[f"model_{k}"] for r in rows])
            row[f"market_{k}"] = _mean([r[f"market_{k}"] for r in rows])
            row[f"{k}_diff"] = _mean(diffs[k])
            b = sorted(boots[k])
            row[f"{k}_diff_ci"] = [b[int(0.025 * (n_boot - 1))], b[int(0.975 * (n_boot - 1))]]
        out.append(row)
    return out


def calibration_pairs(events: list[dict]) -> tuple[list[tuple[float, int]], list[tuple[float, int]]]:
    model, market = [], []
    for e in events:
        model += list(zip(e["model_probs"], e["outcomes"], strict=True))
        market += list(zip(e["market_probs"], e["outcomes"], strict=True))
    return model, market


def calibration_curve(pairs: list[tuple[float, int]], bins: int = 10) -> list[dict]:
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        sel = [(p, o) for p, o in pairs if (lo <= p < hi or (i == bins - 1 and p == 1.0))]
        n = len(sel)
        out.append({
            "bin": f"{lo:.1f}-{hi:.1f}", "n": n,
            "avg_prob": round(sum(p for p, _ in sel) / n, 4) if n else None,
            "win_rate": round(sum(o for _, o in sel) / n, 4) if n else None,
        })
    return out
