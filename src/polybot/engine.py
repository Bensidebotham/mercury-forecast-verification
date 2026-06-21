"""Paper-trading orchestration loop.

Each cycle:
  1. (periodically) rediscover active temperature markets per city
  2. (periodically) refresh ensemble forecasts + live observations
  3. per bucket: book snapshot -> model prob -> taker signal / maker quotes
  4. process maker fills, log everything
  5. settle markets that have resolved
"""

import time
from collections import defaultdict
from datetime import datetime

from rich.console import Console

from polybot import fees  # noqa: F401  (referenced by strategy modules)
from polybot.clients.provider import build_data_provider
from polybot.config import Settings
from polybot.execution import paper
from polybot.forecast import ensemble, nws, obs
from polybot.model import buckets as bucket_model
from polybot.model import calibration as calib
from polybot.storage import db
from polybot.strategy.maker import generate_quotes
from polybot.strategy.signals import taker_signal

console = Console()


class PaperEngine:
    def __init__(self, settings: Settings):
        self.s = settings
        self.data = build_data_provider(settings)
        self.conn = db.connect(settings.db_path)
        self.markets: dict[str, dict] = {}  # token_id -> market row
        self.members: dict[tuple[str, str], list[float]] = {}  # (city, date) -> members
        self.obs_max: dict[tuple[str, str], float | None] = {}
        self.last_discovery = 0.0
        self.last_forecast = 0.0
        # Anti-churn state: forecasts arrive in generations (one per
        # refresh); we record each token's prob per generation, allow at
        # most one taker entry per token per generation, and require the
        # edge to persist across two consecutive generations before
        # buying (unless live observations are driving the signal).
        self.forecast_gen = 0
        self.prob_history: dict[str, dict[int, float]] = {}
        self.last_entry_gen: dict[str, int] = {}
        self.calibration: list[tuple[float, float]] | None = None
        self.refit_calibration()

    def refit_calibration(self) -> None:
        if not self.s.quoting.use_calibration:
            self.calibration = None
            return
        from polybot.config import ROOT

        cal_path = str(ROOT / "data" / "calibration.json")
        fitted = calib.fit_calibration(self.conn)
        if fitted:
            self.calibration = fitted
            calib.save_calibration(fitted, cal_path)  # persist across resets
            knots = ", ".join(f"{x:.2f}->{y:.2f}" for x, y in fitted)
            console.log(f"calibration fit (live): {knots}")
        else:
            # Cold start (e.g. after a clean-slate reset): fall back to the
            # last persisted curve so we don't re-bleed the overconfident
            # region while rebuilding settled samples.
            self.calibration = calib.load_calibration(cal_path)
            if self.calibration:
                knots = ", ".join(f"{x:.2f}->{y:.2f}" for x, y in self.calibration)
                console.log(f"calibration loaded from disk: {knots}")
            else:
                console.log("calibration: no data yet, using raw probs")

    # ---------- data refresh ----------

    def discover(self) -> None:
        rows = self.data.find_weather_markets(self.s.forecast.cities)
        for r in rows:
            # Providers may pre-parse bucket bounds (US); otherwise parse the
            # question (international).
            if r.get("bucket_lo") is not None or r.get("bucket_hi") is not None:
                lo, hi, unit = r["bucket_lo"], r["bucket_hi"], r["unit"]
            else:
                parsed = bucket_model.parse_bucket(r["question"])
                if not parsed:
                    continue
                lo, hi, unit = parsed
                r.update({"bucket_lo": lo, "bucket_hi": hi, "unit": unit})
            self.markets[r["token_id"]] = r
            db.upsert_market(
                self.conn,
                {
                    "token_id": r["token_id"],
                    "event_slug": r["event_slug"],
                    "city": r["city"],
                    "target_date": r["target_date"],
                    "question": r["question"],
                    "bucket_lo": lo,
                    "bucket_hi": hi,
                    "unit": unit,
                    "end_ts": r["end_ts"],
                    "closed": int(r["closed"]),
                },
            )
        self.last_discovery = time.time()
        console.log(f"discovery: {len(self.markets)} bucket markets tracked")

    def refresh_forecasts(self) -> None:
        cities = {c.name: c for c in self.s.forecast.cities}
        targets = {(m["city"], m["target_date"]) for m in self.markets.values()}
        for city_name, date in sorted(targets):
            c = cities.get(city_name)
            if not c:
                continue
            members = ensemble.get_ensemble_members(c.lat, c.lon, c.tz, date, c.unit)
            if members:
                nws_max = nws.get_hourly_daily_max(c.lat, c.lon, c.tz, date)
                if nws_max is not None:
                    median = sorted(members)[len(members) // 2]
                    shift = self.s.forecast.nws_blend * (nws_max - median)
                    members = [m + shift for m in members]
                    if abs(shift) > 1.0:
                        console.log(
                            f"{city_name} {date}: NWS debias {shift:+.1f}F "
                            f"(ensemble median {median:.0f} -> NWS {nws_max:.0f})"
                        )
                self.members[(city_name, date)] = members
                db.insert_forecast(self.conn, city_name, "openmeteo_ensemble", date, members)
            running = obs.get_running_max(c.station, c.tz, date, c.unit)
            self.obs_max[(city_name, date)] = running
            if running is not None:
                db.insert_observation(self.conn, city_name, date, running)
        self.last_forecast = time.time()
        self.forecast_gen += 1
        console.log(
            f"forecasts: {len(self.members)} city-dates with members; "
            f"obs: { {k: v for k, v in self.obs_max.items() if v is not None} }"
        )

    def _is_locked(self, c, date: str) -> bool:
        """Day's high treated as final: either past the hard fallback hour,
        or the observed max has plateaued mid-afternoon (the real lock-in
        window, where the winning bucket is decided but the book is stale)."""
        if obs.is_day_locked(c.tz, date, self.s.forecast.lock_hour_local):
            return True
        hist = self.conn.execute(
            "SELECT ts, obs_max FROM observations WHERE city=? AND target_date=? ORDER BY ts",
            (c.name, date),
        ).fetchall()
        return obs.is_plateaued(
            [(r["ts"], r["obs_max"]) for r in hist],
            c.tz,
            date,
            self.s.forecast.earliest_lock_hour,
            self.s.forecast.plateau_hours,
            time.time(),
        )

    # ---------- one trading cycle ----------

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

        stats = {"signals": 0, "maker_fills": 0, "settled": 0, "books": 0}
        global_remaining = self.s.quoting.max_total_usd - paper.total_open_cost(self.conn)
        today_keys = set()
        for c in self.s.forecast.cities:
            today_keys.add((c.name, datetime.now().astimezone().strftime("%Y-%m-%d")))

        for (city_name, date), token_ids in by_event.items():
            c = cities[city_name]
            key = (city_name, date)
            members = self.members.get(key, [])
            obs_running = self.obs_max.get(key)
            locked = self._is_locked(c, date)
            if not members and not (locked and obs_running is not None):
                continue

            ladder = [(self.markets[t]["bucket_lo"], self.markets[t]["bucket_hi"]) for t in token_ids]
            # METAR hourly maxima undershoot the CLI daily max: buffer the
            # truncation floor; bias the locked-day point estimate upward.
            obs_eff = None
            if obs_running is not None:
                obs_eff = (
                    obs_running + self.s.forecast.locked_bias_f
                    if locked
                    else obs_running - self.s.forecast.obs_buffer_f
                )
            probs = bucket_model.ladder_probabilities(
                members,
                ladder,
                sigma=self.s.forecast.kernel_sigma_f,
                obs_max=obs_eff,
                locked=locked,
                locked_sigma=self.s.forecast.locked_sigma_f,
            )
            exposure = paper.event_exposure(self.conn, token_ids)

            books: dict[str, dict] = {}
            for tid in token_ids:
                book = self.data.get_order_book(tid)
                if book is not None:
                    books[tid] = book
                    stats["books"] += 1
                    db.insert_snapshot(self.conn, tid, book)

            # NB: no event-level "market decided" stand-down. A near-certain
            # bid on ONE bucket often means the market is confidently wrong
            # about WHICH bucket wins — exactly when a cheap, already-decided
            # winner is most mispriced. Edge is judged per bucket below
            # (taker_signal won't buy a bucket whose own price leaves no edge).

            for tid, raw_prob in zip(token_ids, probs):
                book = books.get(tid)
                if book is None:
                    continue
                # Trade on the calibrated probability; log the RAW one so we
                # keep measuring the underlying model's true reliability.
                prob = calib.apply_calibration(raw_prob, self.calibration)
                db.insert_model_prob(self.conn, tid, raw_prob, obs_running)
                row = paper._position(self.conn, tid)
                pos_qty = row["qty"] if row else 0.0
                avg_cost = row["avg_cost"] if row else 0.0

                gen = self.forecast_gen
                hist = self.prob_history.setdefault(tid, {})
                hist.setdefault(gen, prob)

                # Entry gating: once per forecast generation, and the edge
                # must have existed at the previous generation too — unless
                # live obs are driving (obs are ground truth, not noise).
                ask = book.get("best_ask")
                prev_prob = hist.get(gen - 1)
                if self.s.quoting.lock_in_only:
                    # Only enter once the day's high is physically locked in
                    # and observations are driving the signal — no forecast
                    # bets. This is a speed/data edge, not a prediction edge.
                    confirmed = locked and obs_running is not None
                else:
                    confirmed = obs_running is not None or (
                        prev_prob is not None
                        and ask is not None
                        and prev_prob - ask >= self.s.quoting.min_edge_to_quote
                    )
                can_enter = self.last_entry_gen.get(tid) != gen and confirmed

                budget = min(
                    self.s.quoting.max_event_usd - exposure, global_remaining
                )
                sig = taker_signal(
                    tid, prob, book, self.s.quoting, pos_qty, avg_cost,
                    event_budget_usd=max(0.0, budget),
                )
                if sig and (sig.side == "SELL" or can_enter):
                    paper.execute_taker(self.conn, sig, self.s.quoting)
                    if sig.side == "BUY":
                        exposure += sig.size * sig.price
                        global_remaining -= sig.size * sig.price
                        self.last_entry_gen[tid] = gen
                    stats["signals"] += 1
                    console.log(
                        f"TAKER {sig.side} {sig.size:.0f} @ {sig.price:.3f} "
                        f"(cal {prob:.3f}, raw {raw_prob:.3f}, edge {sig.edge:+.3f}) "
                        f"{self.markets[tid]['question'][:55]}"
                    )

                stats["maker_fills"] += paper.check_maker_fills(self.conn, tid, book, self.s.quoting)
                # Lock-in-only mode harvests a speed edge, not a spread edge —
                # no resting maker quotes, so the P&L is a clean read on lock-in.
                if self.s.quoting.lock_in_only:
                    paper.refresh_maker_orders(self.conn, tid, [], prob)
                    continue
                quotes = generate_quotes(
                    tid, prob, book, self.s.quoting, pos_qty,
                    event_budget_usd=max(
                        0.0,
                        min(self.s.quoting.max_event_usd - exposure, global_remaining),
                    ),
                )
                paper.refresh_maker_orders(self.conn, tid, quotes, prob)

        stats["settled"] = self.settle_resolved()
        if stats["settled"]:
            self.refit_calibration()  # learn from the new outcomes
        return stats

    def settle_resolved(self) -> int:
        # Settlement is driven by what we HOLD, not the closed flag:
        # discovery can mark a market closed=1 (from Gamma's per-market
        # flag) before it ever settles, which would orphan the position.
        # Catch any past-end market we still have qty in, or that is
        # closed but not yet recorded in settlements.
        rows = self.conn.execute(
            """SELECT m.token_id, m.event_slug, m.question
               FROM markets m
               WHERE m.end_ts IS NOT NULL AND m.end_ts + 3600 < ?
                 AND m.token_id NOT IN (SELECT token_id FROM settlements)
                 AND (m.closed = 0
                      OR EXISTS (SELECT 1 FROM positions p
                                 WHERE p.token_id = m.token_id AND p.qty > 0))""",
            (time.time(),),
        ).fetchall()
        if not rows:
            return 0
        by_token = {r["token_id"]: r for r in rows}
        outcomes = self.data.get_resolutions(rows)
        settled = 0
        for tid, outcome in outcomes.items():
            if outcome is None or tid not in by_token:
                continue
            pnl = paper.settle_market(self.conn, tid, outcome)
            self.conn.execute(
                "UPDATE markets SET closed=1, outcome=? WHERE token_id=?", (outcome, tid)
            )
            self.conn.commit()
            if pnl != 0:
                console.log(
                    f"SETTLED {by_token[tid]['question'][:60]} -> {outcome} (pnl {pnl:+.2f})"
                )
            self.markets.pop(tid, None)
            settled += 1
        return settled

    # ---------- main loop ----------

    def run(self, cycles: int | None = None) -> None:
        self.discover()
        self.refresh_forecasts()
        n = 0
        while cycles is None or n < cycles:
            started = time.time()
            try:
                stats = self.cycle()
                console.log(
                    f"cycle {n}: books={stats['books']} taker={stats['signals']} "
                    f"maker_fills={stats['maker_fills']} settled={stats['settled']}"
                )
            except Exception as exc:  # never die mid-loop; log and continue
                console.log(f"[red]cycle error: {exc!r}[/red]")
            n += 1
            if cycles is None or n < cycles:
                time.sleep(max(1.0, self.s.paper.cycle_seconds - (time.time() - started)))
