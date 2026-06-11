"""Phase 4: maker quote generation.

Post limit orders at model price +/- margin in undersupplied buckets.
Makers pay zero fees (intl) or earn rebates (US) — we get paid to
supply the liquidity nobody else wants to.
"""

from dataclasses import dataclass

from polybot.config import QuotingConfig


@dataclass
class Quote:
    token_id: str
    side: str  # "BUY" | "SELL"
    price: float
    size: float


def generate_quotes(
    model_prob: float, book: dict, cfg: QuotingConfig
) -> list[Quote]:
    """Produce desired resting orders for one bucket.

    TODO(phase 4):
    - skip if |model_prob - mid| < cfg.min_edge_to_quote
    - quote inside the spread at model_prob +/- cfg.margin
    - size from cfg.max_position_usd and book depth
    - inventory/risk limits across the bucket ladder (adjacent
      buckets are correlated — laddering cuts both ways)
    """
    raise NotImplementedError
