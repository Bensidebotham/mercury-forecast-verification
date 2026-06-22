"""Paper rewards-MM engine for Polymarket US incentive-program markets.

Decoupled from the weather machinery: no forecasts, no lock state. Each cycle
snapshots books for discovered incentive-program markets, selects the most
reward-dense eligible ones (model.market_select), quotes them two-sided via the
existing market_maker policy (fair value = book mid, model_prob=None), and
accrues an optimistic/pessimistic reward range. Reuses execution/paper.py for
simulated fills, inventory, and settlement. Writes to data/rewards.sqlite3.

These are fast in-play sports/esports markets (the only ones with live reward
programs — see the spec REVISION), so adverse selection is EXPECTED to be
material. The simulator exists to measure whether reward income beats it."""

import time

from rich.console import Console

from polybot.clients.us import PolymarketUS
from polybot.config import ROOT, Settings
from polybot.execution import paper
from polybot.model import market_select
from polybot.storage import db
from polybot.strategy import market_maker as mm

console = Console()


class RewardsEngine:
    def __init__(self, settings: Settings, client=None, db_path: str | None = None):
        self.s = settings
        self.r = settings.rewards
        self.client = client if client is not None else PolymarketUS.from_env()
        if self.client is None:
            raise RuntimeError("Polymarket US credentials required (set them in .env)")
        path = db_path or str(ROOT / self.r.db_path)
        self.conn = db.connect(path)
        self.markets: dict[str, dict] = {}   # token_id -> reward-market row
        self.last_discovery = 0.0

    def discover(self) -> None:
        rows = self.client.find_incentivized_markets(self.r.discovery_limit)
        for row in rows:
            self.markets[row["token_id"]] = row
            db.upsert_reward_market(self.conn, row)
        self.last_discovery = time.time()
        console.log(f"discovery: {len(self.markets)} incentivized markets tracked")

    def _recent_snapshots(self, token_id: str, limit: int = 60) -> list[tuple]:
        rows = self.conn.execute(
            "SELECT ts, best_bid, best_ask, bid_depth, ask_depth FROM book_snapshots"
            " WHERE token_id=? ORDER BY ts DESC LIMIT ?",
            (token_id, limit),
        ).fetchall()
        return [(r["ts"], r["best_bid"], r["best_ask"], r["bid_depth"], r["ask_depth"]) for r in rows]

    def cycle(self) -> dict:
        now = time.time()
        if now - self.last_discovery > self.r.discovery_interval_minutes * 60:
            self.discover()

        stats = {"books": 0, "selected": 0, "quotes": 0, "no_quote": 0, "fills": 0,
                 "reward_opt": 0.0, "reward_pess": 0.0, "settled": 0}

        # 1. snapshot every tracked market + process fills from last cycle's quotes.
        #    Cache books so step 3 reuses them instead of re-fetching (signed HTTP).
        books: dict[str, dict] = {}
        for tid in list(self.markets):
            book = self.client.get_order_book(tid)
            if book is None:
                continue
            books[tid] = book
            stats["books"] += 1
            db.insert_snapshot(self.conn, tid, book)
            stats["fills"] += paper.check_maker_fills(self.conn, tid, book, self.s.quoting)

        # 2. select the most reward-dense eligible markets
        scored = [
            market_select.score_market(
                tid, self._recent_snapshots(tid), self.markets[tid]["reward"], now, self.r
            )
            for tid in self.markets
        ]
        selected = market_select.select_markets(scored, self.r.max_markets)
        stats["selected"] = len(selected)

        # 3. quote the selected markets at/near the touch; estimate reward range; rest.
        for tid in selected:
            m = self.markets[tid]
            book = books.get(tid)
            if book is None:
                continue
            inv = paper.position_qty(self.conn, tid)
            quotes = mm.reward_quotes(
                tid, book, self.r.capital_usd, m["tick_size"],
                self.r.quote_ticks_behind, tuple(self.r.reward_band), inv,
            )
            paper.refresh_maker_orders(self.conn, tid, quotes, 0.0)
            if not quotes:
                stats["no_quote"] += 1  # e.g. mid outside reward_band, or no book sides
                continue
            stats["quotes"] += len(quotes)
            opt, pess = mm.estimate_reward_range(
                quotes, book, m["reward"], m["tick_size"], self.r.cycle_seconds,
                self.r.opt_competitor_factor, self.r.pess_competitor_factor,
                self._period_seconds(m["reward"].get("period")),
            )
            db.insert_reward_estimate(self.conn, tid, opt, pess)
            stats["reward_opt"] += opt
            stats["reward_pess"] += pess
        self.conn.commit()

        stats["settled"] = self._settle_resolved()
        return stats

    def _period_seconds(self, period: str | None) -> float:
        """Seconds the reward pool is paid over, by program period. 'live' uses the
        configured (assumed) in-play window; everything else defaults to a day."""
        return self.r.live_period_seconds if period == "live" else 86400.0

    def _settle_resolved(self) -> int:
        held = [r["token_id"] for r in self.conn.execute(
            "SELECT token_id FROM positions WHERE qty != 0"
            " AND token_id NOT IN (SELECT token_id FROM settlements)"
        ).fetchall()]
        if not held:
            return 0
        outcomes = self.client.get_category_resolutions(held)
        settled = 0
        for tid, outcome in outcomes.items():
            if outcome is None:
                continue
            paper.settle_market(self.conn, tid, outcome)
            self.conn.execute(
                "UPDATE reward_markets SET closed=1, outcome=? WHERE token_id=?", (outcome, tid)
            )
            self.conn.commit()
            self.markets.pop(tid, None)
            settled += 1
        return settled

    def run(self, cycles: int | None = None) -> None:
        self.discover()
        n = 0
        while cycles is None or n < cycles:
            started = time.time()
            try:
                s = self.cycle()
                console.log(
                    f"cycle {n}: books={s['books']} selected={s['selected']} "
                    f"quotes={s['quotes']} fills={s['fills']} "
                    f"reward=[{s['reward_pess']:.3f}..{s['reward_opt']:.3f}] settled={s['settled']}"
                )
            except Exception as exc:  # never die mid-loop
                console.log(f"[red]cycle error: {exc!r}[/red]")
            n += 1
            if cycles is None or n < cycles:
                time.sleep(max(1.0, self.r.cycle_seconds - (time.time() - started)))


def rewards_report(conn) -> dict:
    """Net = reward range − adverse selection − fees (spec §9). Reports both
    bounds; the go/no-go gate requires net_pess > 0 over a validation window."""
    est = conn.execute(
        "SELECT COALESCE(SUM(est_opt),0) o, COALESCE(SUM(est_pess),0) p FROM reward_estimates"
    ).fetchone()
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
    # Inventory PnL = realized (settlement + closed-out trades, already net of fees)
    # + unrealized mark. Reported as `adverse_selection_pnl` so that, by construction,
    # reward + adverse_selection_pnl == net for each bound. settlement_pnl and fees_paid
    # are informational sub-components already contained within adverse_selection_pnl.
    adverse = realized + unreal
    return {
        "reward_opt": est["o"],
        "reward_pess": est["p"],
        "adverse_selection_pnl": adverse,
        "settlement_pnl": settle,       # informational (subset of adverse)
        "unrealized": unreal,           # informational (subset of adverse)
        "fees_paid": fills["f"],        # informational (already inside adverse via realized)
        "net_opt": est["o"] + adverse,
        "net_pess": est["p"] + adverse,
        "fills": fills["n"],
        "open_positions": len(open_pos),
    }
