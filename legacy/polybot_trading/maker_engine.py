"""Paper market-making engine (phase 2 of the MM build).

Runs two-sided maker quotes against live books, simulates fills + inventory,
and accrues *estimated* liquidity rewards — so we can see the P&L attribution
(rewards vs spread/rebate vs adverse-selection) before any real capital.

Reuses PaperEngine's discovery / forecast / settlement machinery; overrides
the trading cycle for maker logic. Writes to a SEPARATE db (data/maker.sqlite3)
so it doesn't collide with the taker run.
"""

import time
from collections import defaultdict

from rich.console import Console

from polybot.clients import clob
from polybot.config import ROOT, Settings
from polybot.engine import PaperEngine
from polybot.execution import paper
from polybot.model import buckets as bucket_model
from polybot.model import calibration as calib
from polybot.storage import db
from polybot.strategy import market_maker as mm

console = Console()


class MakerEngine(PaperEngine):
    def __init__(self, settings: Settings, db_path: str | None = None):
        self.s = settings
        self.conn = db.connect(db_path or str(ROOT / "data" / "maker.sqlite3"))
        self.markets = {}
        self.members = {}
        self.obs_max = {}
        self.last_discovery = 0.0
        self.last_forecast = 0.0
        self.forecast_gen = 0
        self.prob_history = {}
        self.last_entry_gen = {}
        # model used only as a fair-value anchor; calibrated if available
        self.calibration = calib.load_calibration(str(ROOT / "data" / "calibration.json"))

    def cycle(self) -> dict:
        now = time.time()
        if now - self.last_discovery > self.s.paper.discovery_interval_minutes * 60:
            self.discover()
        if now - self.last_forecast > self.s.forecast.refresh_interval_minutes * 60:
            self.refresh_forecasts()

        cities = {c.name: c for c in self.s.forecast.cities}
        by_event: dict[tuple[str, str], list[str]] = defaultdict(list)
        for tid, m in self.markets.items():
            by_event[(m["city"], m["target_date"])].append(tid)

        stats = {"quotes": 0, "fills": 0, "reward": 0.0, "books": 0, "settled": 0}
        cyc = self.s.paper.cycle_seconds

        for (city_name, date), token_ids in by_event.items():
            c = cities[city_name]
            members = self.members.get((city_name, date), [])
            obs_running = self.obs_max.get((city_name, date))
            locked = self._is_locked(c, date)

            # model probs (calibrated) as a fair-value anchor — optional
            obs_eff = None
            if obs_running is not None:
                obs_eff = (
                    obs_running + self.s.forecast.locked_bias_f
                    if locked
                    else obs_running - self.s.forecast.obs_buffer_f
                )
            ladder = [(self.markets[t]["bucket_lo"], self.markets[t]["bucket_hi"]) for t in token_ids]
            if members or (locked and obs_running is not None):
                raw_probs = bucket_model.ladder_probabilities(
                    members, ladder, self.s.forecast.kernel_sigma_f, obs_eff, locked,
                    self.s.forecast.locked_sigma_f,
                )
            else:
                raw_probs = [None] * len(token_ids)

            # $1,000/day per EVENT, pro-rated across the event's buckets
            pool_per_bucket = self.s.quoting.mm_daily_pool_usd / max(1, len(token_ids))

            for tid, raw in zip(token_ids, raw_probs):
                book = clob.get_order_book(tid)
                if book is None:
                    continue
                stats["books"] += 1
                db.insert_snapshot(self.conn, tid, book)
                model_prob = (
                    calib.apply_calibration(raw, self.calibration) if raw is not None else None
                )
                # fills from last cycle's resting quotes
                stats["fills"] += paper.check_maker_fills(self.conn, tid, book, self.s.quoting)
                inv = paper.position_qty(self.conn, tid)
                quotes = mm.maker_quotes(tid, model_prob, book, self.s.quoting, inv, locked)
                if quotes:
                    comp = (
                        book.get("bid_depth", 0) + book.get("ask_depth", 0)
                    ) * self.s.quoting.mm_competitor_factor
                    r = mm.estimate_reward(
                        quotes, book, pool_per_bucket,
                        self.s.quoting.mm_reward_discount, comp, cyc,
                    )
                    self.conn.execute(
                        "INSERT INTO maker_rewards VALUES (?,?,?)", (now, tid, r)
                    )
                    stats["reward"] += r
                    stats["quotes"] += len(quotes)
                paper.refresh_maker_orders(
                    self.conn, tid, quotes, model_prob if model_prob is not None else 0.0
                )
            self.conn.commit()

        stats["settled"] = self.settle_resolved()
        return stats

    def run(self, cycles: int | None = None) -> None:
        self.discover()
        self.refresh_forecasts()
        n = 0
        while cycles is None or n < cycles:
            started = time.time()
            try:
                s = self.cycle()
                console.log(
                    f"cycle {n}: books={s['books']} quotes={s['quotes']} "
                    f"fills={s['fills']} reward+=${s['reward']:.2f} settled={s['settled']}"
                )
            except Exception as exc:
                console.log(f"[red]cycle error: {exc!r}[/red]")
            n += 1
            if cycles is None or n < cycles:
                time.sleep(max(1.0, self.s.paper.cycle_seconds - (time.time() - started)))


def maker_report(db_path: str) -> dict:
    """P&L attribution: rewards vs spread/rebate vs adverse selection."""
    conn = db.connect(db_path)
    reward = conn.execute("SELECT COALESCE(SUM(est_reward),0) v FROM maker_rewards").fetchone()["v"]
    realized = conn.execute("SELECT COALESCE(SUM(realized_pnl),0) v FROM positions").fetchone()["v"]
    settle = conn.execute("SELECT COALESCE(SUM(pnl),0) v FROM settlements WHERE qty!=0").fetchone()["v"]
    fills = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(fee),0) f FROM paper_fills").fetchone()
    open_pos = conn.execute(
        """SELECT p.qty, p.avg_cost,
                  (SELECT best_bid FROM book_snapshots b WHERE b.token_id=p.token_id
                   ORDER BY ts DESC LIMIT 1) mark
           FROM positions p WHERE p.qty != 0"""
    ).fetchall()
    unreal = sum(r["qty"] * ((r["mark"] or r["avg_cost"]) - r["avg_cost"]) for r in open_pos)
    # spread/rebate component = realized minus the part that came from settlement
    spread_rebate = realized - settle
    return {
        "reward_income": reward,
        "spread_rebate_pnl": spread_rebate,
        "adverse_selection_pnl": settle,  # residual inventory outcome at resolution
        "unrealized": unreal,
        "net": reward + realized + unreal,
        "fills": fills["n"],
        "rebates_paid": fills["f"],
        "open_positions": len(open_pos),
    }
