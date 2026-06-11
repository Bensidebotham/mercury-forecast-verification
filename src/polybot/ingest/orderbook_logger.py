"""Phase 1: snapshot weather-market order books on a loop.

Goal: ~1 week of real spread/depth data on sub-10c contracts. This
answers research open question #2 (the 1,300-1,800 bps half-spread
claim failed verification — measure it ourselves before sizing).
"""

from polybot.config import Settings


def run_logger(settings: Settings) -> None:
    """Discover weather markets, then every snapshot_interval_seconds:
    fetch each book, compute mid/spread/depth-at-levels, persist a
    snapshot row via storage.db.

    TODO(phase 1): implement loop; tolerate transient HTTP errors;
    log a one-line summary per cycle.
    """
    raise NotImplementedError
