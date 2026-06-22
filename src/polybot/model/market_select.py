"""Market selection for the rewards-MM simulator.

Repointed from the original slow-market thesis (see the spec REVISION): live
Polymarket US reward programs attach only to fast in-play sports/esports markets,
so we select markets that (a) have an active liquidity program and (b) have a
live book — ranked by reward density (pool per unit of target size). Realized
midpoint volatility is computed for REPORTING/attribution only; it does not
filter, because there are no slow incentivized markets to prefer.

Pure functions; the engine feeds in stored book snapshots + the reward params."""

import statistics
from dataclasses import dataclass

from polybot.config import RewardsConfig


@dataclass
class MarketScore:
    token_id: str
    midpoint_vol: float      # realized stdev of mid over the window (report only)
    typical_depth: float     # median per-snapshot min(bid_depth, ask_depth)
    n_snapshots: int
    attractiveness: float    # pool_usd / target_size (reward density); higher = better
    eligible: bool


def score_market(
    token_id: str,
    snapshots: list[tuple],   # (ts, best_bid, best_ask, bid_depth, ask_depth)
    reward: dict | None,
    now: float,
    cfg: RewardsConfig,
) -> MarketScore:
    """Score one incentivized market for quoting suitability."""
    usable = [s for s in snapshots if s[1] is not None and s[2] is not None]
    n = len(usable)
    mids = [(s[1] + s[2]) / 2 for s in usable]
    depths = [min(s[3] or 0.0, s[4] or 0.0) for s in usable]
    vol = statistics.pstdev(mids) if len(mids) >= cfg.min_snapshots else 0.0
    typical_depth = statistics.median(depths) if depths else 0.0
    attractiveness = (
        reward["pool_usd"] / reward["target_size"]
        if reward and reward.get("target_size")
        else 0.0
    )
    eligible = reward is not None and typical_depth > 0.0
    return MarketScore(
        token_id=token_id, midpoint_vol=vol, typical_depth=typical_depth,
        n_snapshots=n, attractiveness=attractiveness, eligible=eligible,
    )


def select_markets(scored: list[MarketScore], max_markets: int) -> list[str]:
    """Token ids of the most reward-dense eligible markets, capped at max_markets.

    Deterministic: ties on attractiveness break by token_id."""
    eligible = sorted(
        (s for s in scored if s.eligible),
        key=lambda s: (-s.attractiveness, s.token_id),
    )
    return [s.token_id for s in eligible[:max_markets]]
