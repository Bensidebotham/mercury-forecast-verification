# Rewards-MM Simulator on Slow Polymarket US Markets — Design

**Date:** 2026-06-21
**Status:** Approved design, pre-implementation
**Supersedes strategic direction of:** the weather/temperature taker+maker strategy (see
`docs/research-calibration-postmortem-2026-06-21.md`), which lost −$421.62 in paper trading
because its forecast model had no durable predictive edge.

---

## 1. Why this pivot

The weather bot did not fail on infrastructure — discovery, book snapshots, the paper
engine, calibration, and sizing guards all work and are reusable. It failed on **edge**: the
model's probabilities were directionally wrong (theoretical +$78 became −$4,662 realized), so
the market priced the contracts better than we did.

A market scan (June 2026) of the alternatives the user raised confirmed the same trap is worse
elsewhere, and is gated by the regulated venue we must use (**Polymarket US**, CFTC-regulated,
`api.polymarket.us`, Ed25519 keys):

- **5/15-min crypto up/down** — near-random direction, wide spreads (~400+ bps), a latency
  game against HFT; exists only on international `polymarket.com`, likely not listed on the
  regulated US venue. Worst option.
- **World Cup / sports** — can't beat the sharp closing line (Pinnacle efficiency R²≈0.997);
  cross-venue arb needs Pinnacle/Betfair, both geo-blocked for US persons; Polymarket US's
  *regulated* sports product is parlay-style CAOCs, not clean single-match books. Weak.

The decisive finding: **Polymarket US runs a Liquidity Incentive Program paying $1,000/day per
event, eligible by default, in four non-sports categories — Climate, Macro, Politics, Culture.**
(Docs: `docs.polymarket.us/incentives/liquidity`.) This makes the viable edge **structural
(rewards capture), not predictive.** A rewards-farming maker does not need to pick winners — it
needs to (1) quote two-sided tightly enough to score, and (2) avoid being destroyed by adverse
selection.

**Chosen approach (B):** a rewards-MM strategy on **slow Politics/Macro/Culture markets** —
chosen over Climate because slow, far-resolving markets have minimal intraday surprise, which
structurally minimizes the adverse selection that killed the weather maker (a documented 2.5¢
adverse move wipes a full day's reward).

**Validation (chosen):** simulate rewards in paper first — no real money — and graduate only
if simulated net is positive.

**Capital assumption (chosen):** $100–500 probe scale.

---

## 2. Objective & definition of success

Build a **paper simulator** estimating, for a given capital level, the net daily PnL of
resting two-sided maker quotes on slow Politics/Macro/Culture markets:

```
net = simulated_rewards − simulated_adverse_selection_pnl − fees
```

At $100–500 capital, rewards are intrinsically tiny (a sub-1% share of a $1,000/day pool).
**Phase 1 is therefore not about proving income — it is about proving the *sign* and the
*machinery*:** that on genuinely slow markets, rewards exceed adverse selection (net > 0),
reversing the weather maker's outcome. Scaling capital is a separate, later decision, gated on
a positive simulated net.

**Go/no-go gate:** several days of simulated net > 0 on the selected slow markets, with the
reward estimate's uncertainty range (see §6) still net-positive at its pessimistic bound.

---

## 3. Phase 0 — API capability gate (hard precondition, no money)

A read-only spike against `api.polymarket.us` using the existing `clients/us.py`. **The
simulator is not built until this passes.**

Verify:
1. List markets by category; confirm Politics / Macro / Culture are present and which markets
   carry reward parameters.
2. Fetch per-market reward fields: pool size, `rewardsMaxSpread`, `rewardsMinSize`, target
   size, discount factor.
3. Confirm live order books are readable for these markets.
4. Confirm (without placing) that maker-order endpoints exist for our keys.

**Exit criterion:** reward parameters are exposed via the API. If they are not, the simulator
cannot be made accurate and the effort stops here — cheaply.

---

## 4. Components (new vs. reused)

| Module | Status | Responsibility |
|---|---|---|
| `clients/us.py` | reuse | discovery, book snapshots, reward params |
| `storage/db.py` | reuse / extend | persist quotes, simulated rewards, simulated fills, daily net |
| `dashboard.py` | reuse / extend | live view of per-market net |
| `analysis/edge.py` | reuse / extend | go/no-go reporting (reward range vs adverse PnL vs net) |
| `execution/paper.py` | reuse | simulated fills/positions for the adverse-selection side |
| `model/slowness.py` | **new** | slow/stable market classifier (adverse-selection risk score) |
| `model/reward_sim.py` | **new** | replicate Polymarket US per-second scoring → pro-rata daily reward |
| `strategy/rewards_maker.py` | **new** | quoting policy optimized to *score*, not to win bets |
| `rewards_engine.py` | **new** | the cycle loop (parallel to existing `maker_engine.py`) |

Each new unit has a single purpose and a defined interface:
- `slowness.py`: `score_market(market, book_history) -> AdverseRiskScore` — no I/O, pure.
- `reward_sim.py`: `simulate_daily_reward(our_quotes, book, reward_params) -> RewardRange` — pure.
- `rewards_maker.py`: `desired_quotes(market, book, capital, reward_params) -> list[Quote]` — pure.
- `rewards_engine.py`: orchestrates client I/O, calls the three pure units, persists via `db.py`.

---

## 5. Market selection — `model/slowness.py`

Score each **reward-eligible** Politics/Macro/Culture market for **adverse-selection risk**,
favoring (lower risk = better target):
- low recent midpoint volatility (small realized variance of mid over a trailing window),
- distant resolution date,
- stable/deep order book,
- no imminent known catalyst (heuristic; manual exclusion list acceptable for v1).

Quote only the lowest-risk markets. **This classifier is the strategy's edge** — we earn
rewards where surprises (and therefore fills against us) are rare.

---

## 6. The reward simulator — `model/reward_sim.py` (core IP)

Replicate Polymarket US scoring:

```
score_per_sample = DiscountFactor ^ (ticks_from_best_price) × OrderSize     # per side
day_score        = Σ score over per-second samples held resting
our_reward       = pool × (our_day_score / total_day_score)                  # pro-rata
                   subject to the $1/day floor (sub-$1 forfeited, no rollover)
```

**Dominant accuracy risk (stated up front):** computing `total_day_score` requires every
maker's *qualifying* resting size, but the public book exposes only aggregate depth — not which
resting orders qualify (within `rewardsMaxSpread`, above `rewardsMinSize`), nor per-maker
attribution. Because the user chose simulate-only (declining live calibration), the simulator
**approximates `total_day_score` from observed book depth within the reward spread band** and
**reports a share range — optimistic and pessimistic bounds — not a point estimate.** This is
the simulator's single largest uncertainty and must be surfaced in every report. The go/no-go
gate requires net > 0 even at the *pessimistic* bound.

Per-market reward parameters (pool, discount factor, max spread, min size, target size) are
read live from the API per §3, never hard-coded — they vary by market.

---

## 7. Quoting policy — `strategy/rewards_maker.py`

Objective differs from the existing edge/taker maker: we **want** to rest near best to score,
while capping inventory.
- Place two-sided resting quotes within `rewardsMaxSpread` of the adjusted midpoint, at/above
  `rewardsMinSize`, sized to the capital assumption.
- Re-peg as the midpoint drifts (orders must stay resting across per-second samples to score).
- Cap total inventory per market to bound adverse-selection exposure.

---

## 8. Adverse-selection accounting

Each cycle, where our resting quote would be crossed by incoming book moves, `execution/paper.py`
simulates the fill and books the position. Adverse PnL = mark-to-mid change on filled inventory.
The thesis is that on slow markets this is ≈ 0; the simulator must confirm rewards clear it.

---

## 9. Validation / reporting

Extend `analysis/edge.py` and the dashboard to show, per market and per day:
- simulated reward (optimistic / pessimistic range),
- simulated adverse-selection PnL,
- fees,
- **net** (and net at the pessimistic reward bound).

The go/no-go gate (§2) reads directly off this report.

---

## 10. Testing

Unit tests, matching the existing discipline (22 tests today):
- reward-score formula against known-input fixtures (discount factor, ticks-from-best, size),
- pro-rata share math and the $1/day floor (including forfeit of sub-$1 days),
- the slowness classifier (ordering of synthetic markets by adverse-selection risk),
- adverse-fill accounting (a crossed quote produces the expected position and mark-to-mid PnL),
- optimistic/pessimistic share-range bounds (pessimistic ≤ optimistic; both ≥ 0).

---

## 11. Out of scope (YAGNI)

- Live order placement / real reward accrual (only after the sim proves positive net).
- Live calibration of the simulator against real rewards (explicitly declined; revisit only if
  the share-range uncertainty proves too wide to make a go/no-go call).
- Climate-category quoting (deferred; revisit after slow-market approach is validated).
- Sports / crypto markets (rejected — see §1).
- Capital scaling beyond the $100–500 probe (separate later decision).
