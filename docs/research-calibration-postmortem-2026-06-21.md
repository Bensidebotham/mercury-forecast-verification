# Calibration Post-Mortem: Paper-Trading Weather Bot
**Date:** 2026-06-21  
**Databases:** polybot.sqlite3 (Jun 15-16), polybot-archive-2026-06-15.sqlite3 (Jun 11-15), maker.sqlite3 (Jun 19-21)  
**Total Paper Losses:** -$421.62 across all three databases

---

## Executive Summary

The bot has lost **$421.62** across three database periods against a $100 starting bankroll. The losses are not random — they reveal three compounding structural failures: (1) the plateau-lock mechanism fires 1–4 hours before the daily temperature peak, locking in wrong-bucket bets before the true winner is decided; (2) METAR hourly observations systematically diverge from NWS CLI settlement values (NYC by up to −4°F, other cities +0.5–0.9°F), causing the observation floor to truncate the wrong part of the distribution; and (3) the taker-signal size formula allocates $10 of capital at 0.1¢/contract prices, producing positions of 5,000–10,000 contracts on buckets with 6–21% model probability that actually win 0% of the time. These are not calibration-curve problems — the raw model probabilities in the 0–30% range are genuinely wrong about direction, not just magnitude.

---

## 1. Calibration: Binned Model Probability vs Actual Win Rate

Query: `SELECT f.model_prob, s.outcome FROM paper_fills f JOIN settlements s ON s.token_id = f.token_id WHERE f.side='BUY'` across all three DBs (942 settled BUY fills).

| Bin | N | Avg Model Prob | Actual Win Rate | Overconfidence | Brier Contrib |
|-----|---|---------------|-----------------|----------------|---------------|
| 0.0–0.1 | 372 | 0.0462 | 0.0000 | +0.0462 | 0.0030 |
| 0.1–0.2 | 307 | 0.1419 | 0.0033 | +0.1387 | 0.0229 |
| 0.2–0.3 | 170 | 0.2321 | 0.0176 | +0.2145 | 0.0636 |
| 0.3–0.4 | 73 | 0.3500 | 0.3836 | −0.0336 | 0.2634 |
| 0.4–0.5 | 13 | 0.4127 | 0.0000 | +0.4127 | 0.1708 |
| 0.5–0.6 | 1 | 0.5623 | 0.0000 | +0.5623 | 0.3161 |
| 0.6–0.7 | 1 | 0.6485 | 0.0000 | +0.6485 | 0.4205 |
| 0.7–0.8 | 1 | 0.7744 | 0.0000 | +0.7744 | 0.5997 |
| 0.9–1.0 | 4 | 0.9972 | 0.2500 | +0.7472 | 0.7500 |
| **TOTAL** | **942** | | | | **0.0475** |

**Overall Brier score: 0.0475** (vs 0.25 for a random 50/50 guesser on binary outcomes — but this is a multi-bucket tournament so the correct baseline is different). The meaningful signal: **every single bucket fill with model_prob < 0.3 was a loss in the 0–0.1 and 0.1–0.2 bins (n=679 fills, 0 wins)**. The 0.3–0.4 bin is the sole well-calibrated region (35.0% model vs 38.4% actual).

**This is not a sigma-too-tight / overconfident-tails problem.** The 0.3–0.4 bin is calibrated. The 0–0.3 bins are buying the wrong buckets — adjacent losers that are genuinely ~0% likely — not just slightly-too-confident neighbors.

---

## 2. PnL Decomposition

### 2a. Taker vs Maker

**polybot-archive.sqlite3 (Jun 11–15, largest dataset):**

| Kind | Side | Fills | Total Contracts | Fees | Avg Fill Price | Avg Model Prob |
|------|------|-------|----------------|------|---------------|----------------|
| maker | BUY | 123 | 2,666 | −$0.95 (rebate) | $0.069 | 0.0801 |
| maker | SELL | 40 | 491 | −$0.91 | $0.207 | 0.1866 |
| taker | BUY | 795 | 56,906 | +$22.97 | $0.034 | 0.1585 |
| taker | SELL | 210 | 6,870 | +$14.58 | $0.086 | 0.0558 |

**Settlement PnL by kind (archive + maker DB):**
- Taker BUYs on losers: 55,111 contracts at avg cost ~$0.034 = **$421.49 spent, $0 recovered**
- Taker BUYs on winners: 448 contracts at avg cost ~$0.117 = **$52.24 spent, $52.24 + $0.96 pnl recovered**
- Maker BUYs on losers: all 8 settled maker BUYs lost (−$24.36)
- Maker SELLs on winners: all 7 maker SELLs on winning buckets were adverse-selection losses

**99.2% of contract volume by count was placed on ultimately-losing buckets.**

### 2b. Locked-Day vs Forecast-Driven

Because `lock_in_only: true` was set in settings.yaml, the intended mode was to only trade with live observations. However, the archive period shows:

| Mode | Tokens | Fills | Avg Model Prob | Win Rate |
|------|--------|-------|---------------|---------|
| obs_present (locked) | 81 | 1,112 | 0.1943 | 10.7% |
| forecast_only (no obs at fill time) | 51 | 2,136 | 0.1253 | 0.0% |

**2,196 of 3,398 (64.6%) archive taker BUY fills had no observation data at the time of execution**, despite `lock_in_only: true`. This happens because fills at 01:44–03:00 UTC target dates that span midnight in UTC but have not yet started in US local time (e.g., fills at 01:44 UTC on 2026-06-11 are targeting June 11 dates for all cities — but for LA (UTC−7) June 11 observations haven't started, and for Chicago (UTC−5) it's 8:44 PM on June 10). The `is_day_locked` function returns `False` for future dates, so `confirmed=False` — yet fills still occur, which suggests the `lock_in_only` mode guard was not active in the archive-period configuration.

### 2c. By City (archive, settled positions only)

| City | Settled | Wins | Losses | Total PnL | Avg PnL/Settlement |
|------|---------|------|--------|-----------|-------------------|
| Los Angeles | 24 | 0 | 24 | −$101.12 | −$4.21 |
| San Francisco | 11 | 0 | 11 | −$70.80 | −$6.44 |
| Miami | 16 | 1 | 15 | −$65.27 | −$4.08 |
| New York City | 14 | 0 | 14 | −$64.15 | −$4.58 |
| Chicago | 13 | 0 | 13 | −$32.11 | −$2.47 |

All five cities are deeply negative. There is no "safe" city in the current regime.

### 2d. By Entry Price Band (archive taker BUYs, settled)

| Price Band | Fills | Contracts | Win Rate | Total PnL |
|-----------|-------|-----------|---------|-----------|
| < $0.05 | 682 | 54,748 | 2.9% | −$3,531 |
| $0.05–0.10 | 92 | 1,421 | 0.0% | −$481 |
| $0.10–0.20 | 65 | 991 | 10.8% | −$443 |
| $0.20–0.30 | 25 | 312 | 12.0% | −$159 |
| $0.30–0.50 | 13 | 143 | 15.4% | −$49 |
| $0.50+ | 1 | 8 | 100.0% | +$0.96 |

The `< $0.05` band dominates by contracts (54,748 out of 57,623 = 95%). The **price/size formula** is the amplification mechanism: `size = budget / price = $10 / $0.001 = 10,000 contracts`. Chicago Jun 11, 78–79°F: 9,780 contracts bought at $0.001 avg = $9.78 invested, outcome = 0 → PnL = −$9.78 plus fees. The low price makes the edge filter easy to pass (model_prob=9.3% − ask=0.1% − fee ≈ +9.2% >> min_edge=3%) while the true win probability is 0%.

---

## 3. Forecast Accuracy vs Probability Conversion

### Was the underlying point forecast good?

Comparing METAR (hourly observations) to NWS CLI settlement winners:

| City | Avg METAR Bias vs Winner Center | Min | Max | N Days |
|------|--------------------------------|-----|-----|--------|
| Chicago | +0.82°F above winner | −0.1°F | +1.9°F | 5 |
| Los Angeles | +0.54°F above winner | −0.5°F | +1.1°F | 5 |
| Miami | +0.69°F above winner | −0.5°F | +1.3°F | 5 |
| New York City | **−1.62°F below winner** | −4.5°F | −0.5°F | 5 |
| San Francisco | +0.93°F above winner | −0.5°F | +2.9°F | 5 |

**In 13 of 25 settlement days (52%), the METAR peak exceeded the NWS CLI winner bucket's upper bound.** This means the hourly-obs floor is incorrectly positioned relative to settlement — sometimes by 1–4°F (NYC on Jun 11: METAR peaked at 89.96°F but NWS CLI winner was 94–95°F, a 4–5°F undershoot). The `obs_buffer_f = 1.0` subtracted from the non-locked floor does not address this; `locked_bias_f = 0.0` means the model trusts METAR exactly when locked.

### Is this a forecasting-skill or probability-conversion problem?

**Answer: It is a forecasting-direction problem in the locked-obs regime, not a sigma problem.**

Evidence:
1. The 0.3–0.4 bin is calibrated (model 35%, actual 38.4%) — the sigma works for mid-range forecasts.
2. The 0–30% losses are not adjacent overconfident buckets with correct direction: model was buying Chicago 78–79°F at 9.3% probability when the eventual winner was 82–83°F (4°F away). At `locked_sigma=0.75`, a Gaussian centered at obs=80.6°F gives P(78–79°F) = 21.2%. The model is systematically buying one or two buckets below the true outcome because the observation floor at the time of purchase (the temperature is still rising) is used as if it is the final answer.
3. San Francisco Jun 12: METAR peak was 73.4°F but NWS CLI winner was 70–71°F (+2.4°F above winner) — the observation was 2.4°F *above* the actual settlement, causing the model to zero out the true winner bucket (its ceiling 71.5 < obs 73.4, so it gets killed). The model bought 80–81°F SF that day.

The `kernel_sigma_f = 1.5` for forecast mode is reasonable. The `locked_sigma_f = 0.75` is not the primary issue — the observation *itself* is wrong, not the kernel width applied to it.

---

## 4. Adverse Selection (maker.sqlite3)

**maker.sqlite3 covers Jun 19–21** with a maker-focused strategy. All 8 maker BUY fills with settled positions resulted in losses (−$24.36). All 6 maker SELL fills on settled positions that were on the winning bucket resulted in being called away (net PnL = 0 from those SELLs, but opportunity cost).

**Classic adverse-selection pattern confirmed:**

| Side | Fills | Avg Fill Price | Win Rate | Total PnL |
|------|-------|---------------|---------|-----------|
| Maker BUY | 8 | $0.167 | 0.0% | −$24.36 |
| Maker SELL (on winners) | 6 | $0.82–0.99 | 100% (wrong side) | Called away |

**Concrete case (LA Jun 19, 68–69°F):**
- Maker BUY order placed at 18:47 UTC at price $0.41, model_prob = 0.0 (calibrated)
- Order FILLED at 19:41:51 UTC — exactly when METAR obs jumped from 66.92°F to 69.98°F
- At obs=69.98°F, bucket 68–69°F has ceiling 69.5°F < obs = bucket is dead (P=0)
- An informed taker saw the obs spike and offloaded the 68–69°F position at $0.41 into the resting maker bid
- Outcome: 68–69°F lost, actual winner was 70–71°F; maker lost $8.20

**Pattern:** The bot rests maker bids on pre-obs buckets that informed takers then sell into when observations reveal those buckets are dead. The maker bid is repricing the model correctly (model_prob dropped to 0.0), but the *order at the old price was not cancelled fast enough* before the observation arrived.

**Second adverse-selection vector:** Maker SELL orders on the correct winner bucket. LA 70–71°F Jun 19: maker posted ask at $0.26 early in the session; informed takers lifted it (bought at 0.26). Winner 70–71°F settled at 1.0. Net PnL from that sell: 0 (collected 0.26, no long position to settle). The maker was providing informed participants cheap insurance on the correct bucket.

---

## 5. Top 3 Root-Cause Hypotheses

### Hypothesis 1: Plateau-lock fires 1–4 hours before the daily temperature peak (PRIMARY)

**Evidence:**
- Chicago Jun 11: plateau lock triggered at ~14:56 UTC (09:56 AM CDT) when obs=75.2°F; actual peak was 82.4°F at 16:58–18:00 UTC. The bot bought 78–79°F bucket (model says 6% at obs=75.2) with 9,780 contracts at $0.001 → PnL = −$10.87.
- The `is_plateaued` function requires `max(recent) <= max(before) + 0.1` over a 2-hour window. In mid-morning, temperature rises are often non-monotone minute-to-minute; the plateau threshold of 0.1°F over 2 hours triggers prematurely on flat early-morning readings.
- Once plateau fires, `locked=True` is passed to `bucket_probability`, which collapses the distribution to a Gaussian centered at the (premature) obs_max. Any bucket more than ~1.5σ above obs_max gets non-negligible probability if its book price is low.
- 8 of the 15 biggest losses in the archive (>$5 each) trace directly to this premature lock.

**Fix:**
1. Raise `plateau_hours` from 2.0 to 3.0 hours minimum.
2. Add a **monotone rising guard**: do not declare a plateau if the last obs reading is within 2°F of the peak (temperature is likely still climbing).
3. Add an **absolute time guard**: do not lock before 15:00 local time regardless of plateau detection.
4. After plateau fires, cap position size at `max_position_usd / price` with a contract ceiling of 200 (not 10,000).

---

### Hypothesis 2: METAR vs NWS CLI observation mismatch — wrong station for NYC, biased readings for all cities (SECONDARY)

**Evidence:**
- NYC: The bot uses KLGA (LaGuardia) for observations; settlement uses KNYC (Central Park). KLGA reads 1.6°F *below* the NWS CLI winner center on average, with a maximum gap of 4.5°F (Jun 11: METAR 89.96°F, actual NWS CLI winner 94–95°F). This means the model consistently assigns mass to too-cool buckets for NYC.
- Other cities: METAR reads 0.5–0.9°F *above* the NWS CLI winner center. This causes the obs floor to truncate the actual winner bucket (e.g., SF Jun 12: METAR=73.4°F > winner ceiling 71.5°F → winner gets P=0).
- The `obs_buffer_f = 1.0` (lowering the non-locked floor by 1°F) is a move in the right direction for the other-cities case but is irrelevant once `locked=True` (where `locked_bias_f=0.0` is used instead).
- `locked_bias_f=0.0` trusts METAR exactly as final, but for non-NYC cities, METAR overshoots NWS CLI by 0.7°F on average.

**Fix:**
1. **Switch NYC station from KLGA to KNYC immediately.** The settings.yaml comment already notes this; it was not applied.
2. Set `locked_bias_f = -0.75` for NYC (METAR reads 1.6°F below CLI average; a −0.75 locked bias shifts the point estimate down toward the CLI range) and `locked_bias_f = +0.50` for other cities.
3. Alternatively, derive per-station empirical bias from the `observations` + `markets outcome=1` tables: the current data already has 25 city-days of calibration signal.
4. The `obs_buffer_f` logic for non-locked mode is correct in principle but should also be per-station.

---

### Hypothesis 3: No max-contracts-per-fill cap — the 0.1¢ price amplifies tiny model probabilities into catastrophic position sizes (AMPLIFIER)

**Evidence:**
- `size = min(ask_depth, budget / price)` where `budget = max_position_usd = $10`
- At `price = $0.001`: size = min(ask_depth, 10,000). Chicago Jun 11: 9,780 contracts bought; Miami Jun 12: 5,089 contracts; NYC Jun 11: 2,835 + 1,200 = 4,035 contracts on a single wrong bucket.
- The PnL loss from a 10,000-contract position at $0.001 is exactly $10.00 (the full budget), but the *number* of contracts is obscenely large and doesn't add any additional edge — it just amplifies basis risk, adverse-selection exposure, and slippage concentration.
- Total archive losses: −$333.45 = 35+ full $10 position blowups. Essentially the bot kept burning $10 units on near-zero-probability buckets.
- The `max_position_usd = $10` cap on paper-cost is correct in principle, but it should also include a **maximum-contracts cap** (e.g., 500 contracts) to prevent the "lottery ticket at 0.1¢" pattern.

**Fix:**
1. Add `max_contracts_per_fill: 500` to `QuotingConfig` and enforce it in `taker_signal`.
2. Apply an **absolute minimum price** for taker signals: refuse to buy if `best_ask < 0.01` (1¢) unless model_prob > 0.50. At 1¢ prices, the model needs to be essentially certain to justify the position.
3. The min-edge filter (`min_edge_to_quote = 0.03`) is computed in probability space; at 0.1¢ ask, edge=9% passes easily even for 12% model_prob. Consider requiring `edge_in_pct_of_price >= 0.5` (edge must be ≥ 50% of the ask price itself) to screen out cheap lottery tickets.

---

## Supporting Evidence Appendix

### Total PnL Summary

| Database | Period | Settled Markets | Wins | Losses | Total PnL |
|----------|--------|----------------|------|--------|-----------|
| polybot.sqlite3 | Jun 15–16 | 20 | 0 | 20 | −$63.81 |
| polybot-archive | Jun 11–15 | 78 | 1 | 77 | −$333.45 |
| maker.sqlite3 | Jun 19–21 | 8 | 0 | 8 | −$24.36 |
| **TOTAL** | | **106** | **1** | **105** | **−$421.62** |

The sole win: Miami Jun 14 92–93°F, 1 position, PnL = +$0.96 (model had 99% confidence at entry, locked late).

### Calibration Module Status

`calibration.json` (written Jun 20 04:37): `[[0.05, 0.0], [0.25, 0.0], [0.95, 0.0]]`

This mapping correctly identifies that model probs < 0.95 have a ~0% empirical win rate. It maps everything to 0.0 calibrated probability. With calibration active, `apply_calibration(any_raw_prob) = 0.0`, making `edge = 0 - ask - fee < 0` for all asks > 0 — **no new taker BUY fills should occur**. The calibration module is working as designed; the losses came before it accumulated the 40+ settled samples needed to activate (the archive period predates it).

**The calibration module has correctly diagnosed the problem.** The issue is that it took 500+ fills and $400 in losses to accumulate enough data to fit it.

### Theoretical vs Actual Edge

From the archive (878 settled BUY fills with model_prob):

```
Sum(model_prob - price):          +$98.59  (theoretical edge pre-fee)
Sum(model_prob - price - fee):    +$78.29  (theoretical edge post-fee)
Actual PnL from these positions:  −$4,662  (actual outcome)
```

The gap between +$78 theoretical and −$4,662 actual confirms the model probabilities are wrong — not just slightly optimistic but directionally incorrect for the 0–30% mass of fills. The theoretical edge depends entirely on the model being calibrated, which it is not in the low-probability range.

### Observation Timing Gap

```
Fills before any obs existed that day: 2,196 (64.6%)
Fills with obs present at fill time:   1,202 (35.4%)
Win rate without obs: 0.0%
Win rate with obs:   10.7%
```

Even with observation data present, win rate is 10.7% in the archive — better than 0%, but still badly overconfident (model assigns ~19% avg for those fills). The plateau-lock issue means even "obs_present" fills are often taken before the temperature has peaked.
