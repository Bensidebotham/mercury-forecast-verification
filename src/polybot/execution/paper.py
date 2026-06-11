"""Phase 4: paper execution engine.

Simulates resting orders against live book updates to measure fill
quality (fill rate, adverse selection) before any real capital.
Live engine comes later and only after paper results look good.
"""

from polybot.strategy.maker import Quote


def run_paper_engine(quotes: list[Quote]) -> None:
    """Track simulated orders; mark fills when the live book trades
    through our price; persist fills + mark-to-market PnL.

    TODO(phase 4): implement against the phase-1 snapshot stream
    (or a CLOB websocket for finer fill simulation).
    """
    raise NotImplementedError
