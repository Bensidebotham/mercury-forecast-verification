"""Market-making strategy: get paid to quote, don't predict the winner.

Revenue = liquidity rewards ($1k/day/event on Polymarket US, scored on
resting-order size × proximity to best price) + maker rebate + spread.
Main risk = adverse selection, managed by inventory skew, caps, and
pulling quotes once the day's high is locked in (informed flow picks off
stale quotes then — the inverse of the lock-in taker play).

Pure functions, same style as strategy/maker.py — the engine wires book
data, inventory, and lock state in.
"""

from dataclasses import dataclass

from polybot.config import QuotingConfig


@dataclass
class MMQuote:
    token_id: str
    side: str  # "BUY" | "SELL"
    price: float
    size: float


def _tick(price: float) -> float:
    tick = 0.001 if price < 0.10 else 0.01
    return max(0.001, min(0.999, round(round(price / tick) * tick, 3)))


def fair_value(model_prob: float | None, book: dict, blend: float) -> float | None:
    """Blend book-mid with the model anchor. Mostly mid (rewards are scored
    near mid); the model pulls fair toward its view to defend against
    quoting on the wrong side of a clear mispricing. None if no usable book."""
    bb, ba = book.get("best_bid"), book.get("best_ask")
    if bb is None or ba is None:
        return None
    mid = (bb + ba) / 2
    if model_prob is None:
        return mid
    return (1 - blend) * mid + blend * model_prob


def maker_quotes(
    token_id: str,
    model_prob: float | None,
    book: dict,
    cfg: QuotingConfig,
    inventory_qty: float = 0.0,
    locked: bool = False,
) -> list[MMQuote]:
    """Two-sided resting quotes around fair value, reward-aware.

    - Pull entirely once the day is locked (avoid adverse selection).
    - Only quote inside the reward band (rewards aren't paid outside it).
    - Skew both quotes against inventory to mean-revert to flat.
    - Never cross the book (stay a maker); clamp to just inside the touch
      so we sit near best price for reward scoring without taking.
    """
    if locked and cfg.mm_pull_on_lock:
        return []
    fair = fair_value(model_prob, book, cfg.mm_fair_blend)
    if fair is None:
        return []
    lo, hi = cfg.mm_reward_band
    if not (lo <= fair <= hi):
        return []

    # inventory skew: long -> push quotes down to sell; short -> push up
    cap = max(cfg.mm_max_inventory_usd, 1e-9)
    inv_ratio = max(-1.0, min(1.0, (inventory_qty * fair) / cap))
    skew = cfg.mm_skew * inv_ratio * cfg.mm_half_spread

    bid_px = _tick(fair - cfg.mm_half_spread - skew)
    ask_px = _tick(fair + cfg.mm_half_spread - skew)

    bb, ba = book.get("best_bid"), book.get("best_ask")
    # stay near the touch for reward proximity, but never cross
    if ba is not None:
        bid_px = min(bid_px, _tick(ba - 0.001))
    if bb is not None:
        ask_px = max(ask_px, _tick(bb + 0.001))

    quotes: list[MMQuote] = []
    # suppress the side that would breach the inventory cap
    inv_usd = inventory_qty * fair
    if bid_px > 0 and bid_px < (ba if ba is not None else 1.0) and inv_usd < cfg.mm_max_inventory_usd:
        quotes.append(MMQuote(token_id, "BUY", bid_px, float(int(cfg.mm_size))))
    if ask_px < 1 and ask_px > (bb if bb is not None else 0.0) and inv_usd > -cfg.mm_max_inventory_usd:
        quotes.append(MMQuote(token_id, "SELL", ask_px, float(int(cfg.mm_size))))
    return quotes


def reward_quotes(
    token_id: str,
    book: dict,
    capital_usd: float,
    tick_size: float,
    ticks_behind: int = 0,
    reward_band: tuple[float, float] = (0.05, 0.95),
    inventory_qty: float = 0.0,
) -> list[MMQuote]:
    """Two-sided resting quotes for the rewards-MM strategy: rest AT the touch
    (ticks_behind=0 → max proximity score) or `ticks_behind` ticks back from best
    (less reward, lower fill risk). Sized from capital. Quotes off the live best
    prices (already on the venue tick grid) — NOT off a rounded fair value, so the
    reward score isn't destroyed by a coarse price grid (the bug `_tick` caused).

    Inventory cap = capital_usd: suppress the side that would push |inventory| past it."""
    bb, ba = book.get("best_bid"), book.get("best_ask")
    if bb is None or ba is None:
        return []
    mid = (bb + ba) / 2
    if mid <= 0:
        return []
    lo, hi = reward_band
    if not (lo <= mid <= hi):
        return []
    size = float(max(1, int(capital_usd / mid)))
    bid_px = round(bb - ticks_behind * tick_size, 6)
    ask_px = round(ba + ticks_behind * tick_size, 6)
    inv_usd = inventory_qty * mid
    quotes: list[MMQuote] = []
    if bid_px > 0 and inv_usd < capital_usd:
        quotes.append(MMQuote(token_id, "BUY", bid_px, size))
    if ask_px < 1 and inv_usd > -capital_usd:
        quotes.append(MMQuote(token_id, "SELL", ask_px, size))
    return quotes


def proximity_score(order_price: float, best_price: float, side: str, discount: float) -> float:
    """Reward proximity weight in [0,1]: 1 at the touch, decaying with
    distance via the venue's discount factor. side BUY scores vs best_bid,
    SELL vs best_ask."""
    if best_price is None:
        return 0.0
    dist = abs(order_price - best_price)
    return max(0.0, 1.0 - dist / discount) if discount > 0 else (1.0 if dist == 0 else 0.0)


def estimate_reward(
    quotes: list[MMQuote],
    book: dict,
    daily_pool_usd: float,
    discount: float,
    competitor_depth: float,
    seconds: float,
) -> float:
    """Estimate liquidity reward earned over `seconds` for a two-sided quote.

    our_score = sum(size × proximity), requires BOTH sides (else heavily
    penalized). share = our_score / (our_score + competitor_score), where
    competitor_score is approximated from book depth near the touch.
    Reward = share × pool × (seconds / 86400).
    """
    sides = {q.side for q in quotes}
    if not {"BUY", "SELL"} <= sides:  # single-sided: disqualified/penalized
        return 0.0
    our_score = 0.0
    for q in quotes:
        best = book.get("best_bid") if q.side == "BUY" else book.get("best_ask")
        our_score += q.size * proximity_score(q.price, best, q.side, discount)
    if our_score <= 0:
        return 0.0
    total = our_score + max(0.0, competitor_depth)
    share = our_score / total
    return share * daily_pool_usd * (seconds / 86400.0)


def _ticks_from_best(price: float, best: float | None, tick_size: float) -> int | None:
    """Number of price ticks between an order and the best price on its side."""
    if best is None or tick_size <= 0:
        return None
    return round(abs(price - best) / tick_size)


def _us_score(quotes: list[MMQuote], book: dict, discount: float, tick_size: float) -> float:
    """Polymarket US resting-order score: size × discount^(ticks from best),
    summed across both sides. Requires a two-sided quote (else 0)."""
    if not {"BUY", "SELL"} <= {q.side for q in quotes}:
        return 0.0
    score = 0.0
    for q in quotes:
        best = book.get("best_bid") if q.side == "BUY" else book.get("best_ask")
        ticks = _ticks_from_best(q.price, best, tick_size)
        if ticks is None:
            continue
        score += q.size * (discount ** ticks)
    return score


def estimate_reward_range(
    quotes: list[MMQuote],
    book: dict,
    params: dict,
    tick_size: float,
    seconds: float,
    opt_factor: float,
    pess_factor: float,
    period_seconds: float = 86400.0,
) -> tuple[float, float]:
    """(optimistic, pessimistic) reward for a two-sided quote under the Polymarket US
    scoring model: reward = pool × ourScore / max(targetSize, ourScore + competitorScore)
    × (seconds / period_seconds), where ourScore = Σ size × discount^ticks_from_best.

    The competing qualifying size is unobservable (spec §6), so we bracket it:
      - optimistic: competitor = observed top-of-book depth × opt_factor (light)
      - pessimistic: competitor = max(target_size, observed depth) × pess_factor (heavy)
    The target_size term is a denominator FLOOR: a lone tiny maker cannot capture the
    whole pool. Returns (opt, pess) with opt >= pess >= 0."""
    our = _us_score(quotes, book, params["discount"], tick_size)
    if our <= 0:
        return 0.0, 0.0
    pool = params["pool_usd"]
    target = params["target_size"]
    observed = (book.get("bid_depth", 0.0) or 0.0) + (book.get("ask_depth", 0.0) or 0.0)
    frac = seconds / period_seconds
    opt = pool * our / max(target, our + observed * opt_factor) * frac
    pess = pool * our / max(target, our + max(target, observed) * pess_factor) * frac
    return max(opt, pess), min(opt, pess)
