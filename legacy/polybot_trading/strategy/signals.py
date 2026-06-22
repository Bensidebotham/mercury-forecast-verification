"""Taker signals: model probability vs live book, net of fees.

Two directions on the YES token:
  BUY  — model says the bucket is worth more than the ask
  SELL — model says it's worth less than the bid (only to flatten longs;
         the paper engine holds no naked shorts)
Lock-in trades are the special case where obs_max has zeroed/locked the
distribution and the book hasn't repriced — same code path.
"""

from dataclasses import dataclass

from polybot.config import QuotingConfig
from polybot.fees import trade_fee


@dataclass
class TakerSignal:
    token_id: str
    side: str  # "BUY" | "SELL"
    price: float
    size: float  # contracts
    model_prob: float
    edge: float  # expected value per contract, net of fee


def taker_signal(
    token_id: str,
    model_prob: float,
    book: dict,
    cfg: QuotingConfig,
    position_qty: float = 0.0,
    avg_cost: float = 0.0,
    event_budget_usd: float | None = None,
) -> TakerSignal | None:
    best_ask, ask_depth = book.get("best_ask"), book.get("ask_depth", 0)
    best_bid, bid_depth = book.get("best_bid"), book.get("bid_depth", 0)

    # BUY: pay ask, contract worth model_prob in expectation
    # Skip cheap longshots unless the model is near-certain: at sub-min_taker_price
    # asks the edge filter passes on tiny model probs that historically won ~0%.
    longshot = best_ask is not None and best_ask < cfg.min_taker_price
    if best_ask is not None and ask_depth > 0 and not (
        longshot and model_prob < cfg.longshot_prob_floor
    ):
        fee = trade_fee(cfg.taker_theta, 1, best_ask)
        edge = model_prob - best_ask - fee
        if edge >= cfg.min_edge_to_quote:
            budget = cfg.max_position_usd - position_qty * best_ask
            if event_budget_usd is not None:
                budget = min(budget, event_budget_usd)
            size = min(ask_depth, budget / best_ask if best_ask > 0 else 0)
            size = min(size, cfg.max_contracts_per_fill)  # hard contract cap
            if size >= 1:
                return TakerSignal(token_id, "BUY", best_ask, float(int(size)), model_prob, edge)

    if position_qty > 0 and best_bid is not None and bid_depth > 0:
        fee = trade_fee(cfg.taker_theta, 1, best_bid)
        # SELL to exit a long the model now says is rich
        edge = best_bid - model_prob - fee
        rich = edge >= cfg.min_edge_to_quote
        # Salvage exit: the model has collapsed below half our cost basis
        # (the edge we bought is gone) and the bid still beats fair value —
        # cut the loss instead of riding a dead bucket to zero.
        salvage = (
            avg_cost > 0
            and model_prob < 0.5 * avg_cost
            and best_bid - model_prob - fee > 0
        )
        if rich or salvage:
            size = min(bid_depth, position_qty)
            if size >= 1:
                return TakerSignal(token_id, "SELL", best_bid, float(int(size)), model_prob, edge)
    return None
