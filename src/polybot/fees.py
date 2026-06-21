"""Polymarket US fee curve (eff. 2026-04-03): Fee = theta * C * p * (1-p).

Taker theta = 0.05, maker theta = -0.0125 (a rebate, paid at trade time).
Paper trading applies these so PnL previews the venue we'll go live on.
"""


def trade_fee(theta: float, contracts: float, price: float) -> float:
    """Fee in USD; negative means a rebate received."""
    return theta * contracts * price * (1 - price)
