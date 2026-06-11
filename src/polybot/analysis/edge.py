"""Phase 3: passive backtest — model probabilities vs logged prices.

Gate for everything downstream: only proceed to quoting if persistent
model-vs-market gaps exist AFTER spread costs measured in phase 1.
"""


def edge_report(db_path: str) -> dict:
    """Join logged book snapshots with model distributions; report
    gap size, persistence, and net-of-spread profitability per
    city/bucket.

    TODO(phase 3): implement once phases 1-2 produce data.
    """
    raise NotImplementedError
