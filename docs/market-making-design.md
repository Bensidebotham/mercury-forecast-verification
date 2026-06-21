# Market-Making Strategy — Design Sketch
*Drafted 2026-06-19. The pivot from taker (predict/race) to maker (provide liquidity, get paid for it).*

## Why this is different from everything we tried

The taker strategies (forecast-edge, lock-in) all required **beating the market** — either out-forecasting it or out-racing it to a known outcome. Nine days proved that's hard-to-impossible for a public-data bot in efficient temperature books.

Market-making inverts the problem. **We don't predict the winner. We get paid to quote.** Three revenue streams, none of which require being right about the temperature:

1. **Liquidity rewards (the main prize).** Polymarket US pays **$1,000/day per event** for Climate (weather) markets — split pro-rata among makers by how close to the best price and how large their resting orders are, scored *every second*. Five cities = up to ~$5,000/day in reward pools we compete for. This pays whether or not our quotes ever fill. (Source: docs.polymarket.us/incentives/liquidity, verified 2026-06-10.)
2. **Maker rebate.** Θ = −0.0125 paid at trade time on every fill (Fee = Θ·C·p·(1−p)).
3. **Spread capture.** Buy at our bid, sell at our ask; pocket the difference over many round-trips.

## The one real risk: adverse selection (inventory)

The danger isn't being wrong about temperature — it's getting **picked off**. If we quote both sides and the fair value moves against us, informed traders fill the stale side and we accumulate losing inventory. The whole craft of market-making is managing this:

- **Inventory skew** — as we get long a bucket, lower *both* our quotes to encourage selling and discourage more buying (Avellaneda-Stoikov style). Keeps us mean-reverting to flat.
- **Inventory caps** — hard limit per bucket and per event.
- **Pull quotes when the day locks** — this is the *exact inverse* of the lock-in taker play. Once the daily high is physically in, informed traders know the answer and will pick off our stale quotes. As a maker we **stop quoting** at lock time; as a taker we *entered* then. Same signal, opposite action.

## Where our forecast model is finally useful

The model can't beat the market as a taker, but as a maker it's a **fair-value anchor**, not a predictor:
- Center quotes on a blend of book-mid and model (mostly mid, since rewards are scored near mid).
- When model and mid disagree sharply, **widen or pull** on the side the model thinks is mispriced — defense against adverse selection, not a directional bet.

So nothing built so far is wasted: the forecast layer, calibration, obs/lock detection all feed the maker's risk controls.

## Reward mechanics (what we optimize)

Per docs.polymarket.us/incentives/liquidity:
- Scored every second; reward ∝ order **size** × **proximity to best price** (a "discount factor" penalizes distance).
- **Two-sided required** — single-sided orders are penalized/disqualified.
- **Target size** — a minimum contracts-per-side to qualify.
- Only paid within a price band (intl uses 0.10–0.90 midpoints; US per-event params).
- Pool split pro-rata across all qualifying makers in the event.

Implication for us: quote **both sides, near the touch, at/above target size, only on buckets priced inside the band** (the center/shoulder buckets — *not* the deep tails, which fall outside the band anyway). This is the opposite footprint from the taker strategy, which lived in the tails.

## Economics sketch (why it can work at small size)

- Reward pool: $1,000/day/event. If we capture even a 2% share across 5 events ≈ **$100/day** in rewards alone, independent of fills.
- Our share = our_score / (our_score + competitors'). Thin weather books mean few competing makers → a small bankroll can hold a non-trivial share of the near-touch size.
- Spread + rebate are gravy on top; adverse-selection losses are the cost. Net edge = rewards + spread + rebate − adverse selection − fees.
- **Capital efficiency** is the appeal: rewards scale with *presence*, not with being right, so a disciplined $100–500 maker can earn a steady reward yield where the taker strategy earned nothing.

## What runs now vs. needs the US API key

| Piece | Now (paper, intl book data) | Needs US API key |
|---|---|---|
| Fair value, quote generation, inventory skew, lock-pull | ✅ buildable & testable | — |
| Paper fill simulation against logged books | ✅ (reuse paper engine) | — |
| **Reward accrual** | ⚠️ *estimated* from book depth | ✅ real ($1k/day/event) |
| Live order placement | ❌ | ✅ Ed25519 / `polymarket-us` SDK |

We can paper-test the mechanics and inventory risk immediately. The actual reward income — the main reason to do this — only exists on the real venue, so this is the strategy that finally makes getting your API key worthwhile.

## Build phases

1. **Core quoting logic** (this sketch): fair value, two-sided reward-aware quotes, inventory skew, lock-pull, reward estimator. Pure + tested.
2. **Paper maker engine**: run the quotes against live intl books, simulate fills + inventory + estimated rewards, show net P&L attribution (rewards vs spread vs adverse selection) on the dashboard.
3. **Tune** half-spread / size / skew / band on paper until the attribution shows rewards + spread reliably beat adverse selection.
4. **US client** (`clients/us.py`, Ed25519): same interface as gamma/clob, swap in for a small live pilot once paper looks good.
5. **Live pilot**: small capital, real reward accrual, measure realized yield.

## Key parameters (first guesses, to tune on paper)

- `mm_half_spread`: 0.02 — quote ±2¢ around fair
- `mm_size`: contracts per side (sized to bankroll & target size)
- `mm_max_inventory_usd`: per-bucket inventory cap
- `mm_skew`: inventory skew strength
- `mm_reward_band`: [0.10, 0.90] — only quote buckets priced here
- `mm_fair_blend`: 0.3 — weight on model vs book-mid for fair value
- `mm_pull_on_lock`: true — stop quoting once the day's high is locked
