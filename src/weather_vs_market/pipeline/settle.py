"""Mark stored markets settled once their venue publishes a result.

Only markets already in the store are updated; settlement never invents rows.
"""
import logging
import time

from sqlalchemy import Engine

from weather_vs_market.clients import kalshi
from weather_vs_market.clients import polymarket_history as ph
from weather_vs_market.config import Settings
from weather_vs_market.storage import store

log = logging.getLogger("wvm.settle")


def outcome_from_result(result: str | None) -> int | None:
    if result in ("yes", "no"):
        return 1 if result == "yes" else 0
    return None


def kalshi_outcomes(raw_markets: list[dict], known_uids: set[str]) -> list[tuple[str, int]]:
    out = []
    for raw in raw_markets:
        uid = f"kalshi:{raw['ticker']}"
        outcome = outcome_from_result(raw.get("result"))
        if uid in known_uids and outcome is not None:
            out.append((uid, outcome))
    return out


def settle_kalshi(settings: Settings, engine: Engine) -> int:
    v = store.vmarket
    known = {m["market_uid"] for m in store.read_markets(engine, v.c.venue == "kalshi",
                                                          v.c.settled == 0)}
    n = 0
    for venue_city in settings.venues.kalshi:
        try:
            raw = kalshi.fetch_settled(venue_city.series)
        except Exception as e:
            log.warning("kalshi settled fetch failed for %s: %s", venue_city.series, e)
            continue
        outcomes = kalshi_outcomes(raw, known)
        store.settle_markets(engine, outcomes)
        n += len(outcomes)
    return n


def settle_polymarket(settings: Settings, engine: Engine, now: float | None = None) -> int:
    """Settle past-close Polymarket markets from their (closed) Gamma event."""
    now = now if now is not None else time.time()
    v = store.vmarket
    pending: dict[str, set[str]] = {}
    for m in store.read_markets(engine, v.c.venue == "polymarket", v.c.settled == 0,
                                v.c.close_ts < now):
        pending.setdefault(m["event_key"], set()).add(m["market_uid"])
    n = 0
    for slug, uids in pending.items():
        try:
            ev = ph.fetch_event(slug)
        except Exception as e:
            log.warning("polymarket event fetch failed for %s: %s", slug, e)
            continue
        if ev is None:
            continue
        outcomes = [(f"polymarket:{r['token_id']}", r["outcome"]) for r in ph.parse_event(ev)
                    if r["outcome"] is not None and f"polymarket:{r['token_id']}" in uids]
        store.settle_markets(engine, outcomes)
        n += len(outcomes)
    return n


def run_settle(settings: Settings, engine: Engine) -> dict:
    return {"kalshi": settle_kalshi(settings, engine),
            "polymarket": settle_polymarket(settings, engine)}
