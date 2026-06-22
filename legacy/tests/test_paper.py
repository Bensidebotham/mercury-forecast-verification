from polybot.config import QuotingConfig
from polybot.execution import paper
from polybot.storage import db
from polybot.strategy.maker import Quote
from polybot.strategy.signals import TakerSignal

CFG = QuotingConfig()


def make_conn(tmp_path):
    return db.connect(str(tmp_path / "test.sqlite3"))


def test_taker_fill_creates_position(tmp_path):
    conn = make_conn(tmp_path)
    sig = TakerSignal("tok", "BUY", 0.02, 100, 0.10, 0.08)
    paper.execute_taker(conn, sig, CFG)
    assert paper.position_qty(conn, "tok") == 100
    row = conn.execute("SELECT * FROM positions WHERE token_id='tok'").fetchone()
    assert abs(row["avg_cost"] - 0.02) < 1e-9


def test_maker_fill_requires_cross(tmp_path):
    conn = make_conn(tmp_path)
    paper.refresh_maker_orders(conn, "tok", [Quote("tok", "BUY", 0.05, 100)], 0.07)
    # ask above our bid -> no fill
    assert paper.check_maker_fills(conn, "tok", {"best_ask": 0.06, "ask_depth": 50}, CFG) == 0
    # ask drops through our bid -> fill, haircut applied
    n = paper.check_maker_fills(conn, "tok", {"best_ask": 0.05, "ask_depth": 50}, CFG)
    assert n == 1
    qty = paper.position_qty(conn, "tok")
    assert qty == int(50 * CFG.maker_fill_haircut)


def test_maker_rebate_is_negative_fee(tmp_path):
    conn = make_conn(tmp_path)
    paper.refresh_maker_orders(conn, "tok", [Quote("tok", "BUY", 0.50, 10)], 0.55)
    paper.check_maker_fills(conn, "tok", {"best_ask": 0.50, "ask_depth": 100}, CFG)
    fee = conn.execute("SELECT fee FROM paper_fills").fetchone()["fee"]
    assert fee < 0  # rebate received


def test_settlement_pays_winner(tmp_path):
    conn = make_conn(tmp_path)
    paper.execute_taker(conn, TakerSignal("tok", "BUY", 0.05, 100, 0.20, 0.14), CFG)
    pnl = paper.settle_market(conn, "tok", outcome=1)
    assert abs(pnl - 100 * (1.0 - 0.05)) < 1e-9
    assert paper.position_qty(conn, "tok") == 0


def test_settlement_loser_costs_basis(tmp_path):
    conn = make_conn(tmp_path)
    paper.execute_taker(conn, TakerSignal("tok", "BUY", 0.05, 100, 0.20, 0.14), CFG)
    pnl = paper.settle_market(conn, "tok", outcome=0)
    assert abs(pnl + 100 * 0.05) < 1e-9


def test_cancel_replace_leaves_one_open_set(tmp_path):
    conn = make_conn(tmp_path)
    paper.refresh_maker_orders(conn, "tok", [Quote("tok", "BUY", 0.05, 100)], 0.07)
    paper.refresh_maker_orders(conn, "tok", [Quote("tok", "BUY", 0.06, 100)], 0.08)
    open_orders = conn.execute(
        "SELECT * FROM paper_orders WHERE status='open'"
    ).fetchall()
    assert len(open_orders) == 1
    assert open_orders[0]["price"] == 0.06


def test_event_exposure_caps(tmp_path):
    conn = make_conn(tmp_path)
    paper.execute_taker(conn, TakerSignal("a", "BUY", 0.10, 50, 0.3, 0.1), CFG)
    paper.execute_taker(conn, TakerSignal("b", "BUY", 0.20, 25, 0.4, 0.1), CFG)
    exp = paper.event_exposure(conn, ["a", "b"])
    assert abs(exp - (50 * 0.10 + 25 * 0.20)) < 1e-9


def test_settle_zeroes_position_even_if_stale_settlement_row(tmp_path):
    # regression: a pre-existing qty=0 settlement row must not block a real
    # settlement from zeroing a re-acquired position (INSERT OR REPLACE)
    conn = make_conn(tmp_path)
    # stale zero-row (as if we'd been flat at an earlier settle attempt)
    conn.execute("INSERT INTO settlements VALUES (?,?,?,?,?)", ("tok", 1.0, 0, 0.0, 0.0))
    conn.commit()
    paper.execute_taker(conn, TakerSignal("tok", "BUY", 0.05, 100, 0.20, 0.14), CFG)
    pnl = paper.settle_market(conn, "tok", outcome=0)
    assert abs(pnl + 100 * 0.05) < 1e-9
    assert paper.position_qty(conn, "tok") == 0
    row = conn.execute("SELECT qty, pnl FROM settlements WHERE token_id='tok'").fetchone()
    assert row["qty"] == 100  # real settlement replaced the stale zero row
