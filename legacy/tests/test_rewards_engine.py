from polybot.config import load_settings
from polybot.rewards_engine import RewardsEngine, rewards_report


def _market(tid):
    return {
        "token_id": tid, "event_slug": "", "category": "sports",
        "question": f"q-{tid}", "end_ts": 9_999_999_999.0, "closed": False,
        "tick_size": 0.01,
        "reward": {"pool_usd": 2000.0, "discount": 0.3, "target_size": 15000.0,
                   "period": "live", "program_id": "p"},
    }


STABLE_BOOK = {"best_bid": 0.49, "best_ask": 0.51, "bid_depth": 100, "ask_depth": 100,
               "bids": [[0.49, 100]], "asks": [[0.51, 100]]}


class FakeClient:
    """Stand-in for PolymarketUS: fixed market list, stable book, no resolution."""

    def __init__(self, rows, book):
        self._rows = rows
        self._book = book

    def find_incentivized_markets(self, limit=100):
        return self._rows

    def get_order_book(self, token_id):
        return dict(self._book)

    def get_category_resolutions(self, token_ids):
        return {t: None for t in token_ids}


def test_engine_selects_quotes_and_estimates_reward():
    eng = RewardsEngine(load_settings(), client=FakeClient([_market("m1")], STABLE_BOOK),
                        db_path=":memory:")
    eng.discover()
    s = eng.cycle()
    assert s["selected"] == 1
    assert s["quotes"] == 2  # two-sided
    assert s["reward_opt"] >= s["reward_pess"] >= 0.0

    rep = rewards_report(eng.conn)
    assert rep["reward_opt"] >= rep["reward_pess"] >= 0.0
    assert "net_opt" in rep and "net_pess" in rep
    # I1: the breakdown reconciles — reward + adverse == net for each bound.
    assert abs(rep["reward_opt"] + rep["adverse_selection_pnl"] - rep["net_opt"]) < 1e-9
    assert abs(rep["reward_pess"] + rep["adverse_selection_pnl"] - rep["net_pess"]) < 1e-9


def test_engine_skips_market_without_program():
    nr = _market("nr")
    nr["reward"] = None
    eng = RewardsEngine(load_settings(), client=FakeClient([nr], STABLE_BOOK),
                        db_path=":memory:")
    eng.discover()
    s = eng.cycle()
    assert s["selected"] == 0
    assert s["quotes"] == 0
