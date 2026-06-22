"""Maker quote generation.

Rest limit orders at model price +/- margin. On Polymarket US makers
earn a rebate at trade time plus daily Climate liquidity rewards
($1,000/day per event, scored every second by price/size proximity).
Paper mode rests the same quotes virtually to measure fill quality.
"""

from dataclasses import dataclass

from polybot.config import QuotingConfig


@dataclass
class Quote:
    token_id: str
    side: str  # "BUY" | "SELL"
    price: float
    size: float


def _tick(price: float) -> float:
    """Round to venue tick: 0.001 below 10c, 0.01 above."""
    tick = 0.001 if price < 0.10 else 0.01
    return max(0.001, min(0.999, round(round(price / tick) * tick, 3)))


def generate_quotes(
    token_id: str,
    model_prob: float,
    book: dict,
    cfg: QuotingConfig,
    position_qty: float = 0.0,
    event_budget_usd: float | None = None,
) -> list[Quote]:
    """Two-sided quotes around the model price for one bucket.

    - bid at model - margin, ask at model + margin (ticked, inside [0,1])
    - never bid above the book's best ask (that would be a taker order;
      the taker path handles genuine crossing edge)
    - SELL side only up to current inventory (no naked shorts in paper)
    - sized by max_position_usd
    """
    quotes: list[Quote] = []
    bid_px = _tick(model_prob - cfg.margin)
    ask_px = _tick(model_prob + cfg.margin)

    best_ask = book.get("best_ask")
    if bid_px > 0 and (best_ask is None or bid_px < best_ask):
        budget = cfg.max_position_usd - position_qty * bid_px
        if event_budget_usd is not None:
            budget = min(budget, event_budget_usd)
        max_qty = budget / bid_px if bid_px > 0 else 0
        size = float(int(min(max_qty, 200)))
        if size >= 1:
            quotes.append(Quote(token_id, "BUY", bid_px, size))

    if position_qty >= 1 and ask_px < 1:
        best_bid = book.get("best_bid")
        if best_bid is None or ask_px > best_bid:
            quotes.append(Quote(token_id, "SELL", ask_px, float(int(position_qty))))

    return quotes[: cfg.max_open_orders_per_market]
