# Evaluation protocol (v1)

Written and committed **before** any test-window data was scored. The commit that
adds this file predates the commit that adds `results/backtest.json`; `git log`
on the two files is the audit trail. Any change after that is a new protocol
version with its own results, and both are reported.

## Question

At a fixed time before the day starts, is a bias-corrected weather model's
probability for each temperature bucket more accurate than the market's?
"The market is better" is an acceptable answer.

## Data

| What | Source | Notes |
|---|---|---|
| Kalshi ladders and results | `/historical/markets` + `/markets?status=settled` | NY (KNYC), Chicago (KMDW), Miami (KMIA), LA (KLAX) |
| Kalshi prices | hourly candlesticks (bid/ask close) | `/historical/markets/{t}/candlesticks` before the cutoff, `/series/.../candlesticks` after |
| Polymarket ladders and results | Gamma `/events?slug=` | NYC (KLGA), Chicago (KORD), Miami (KMIA), LA (KLAX), SF (KSFO) |
| Polymarket prices | CLOB `/prices-history`, hourly | a trade/mid price, not a bid/ask |
| Forecasts | Open-Meteo Previous Runs API | `gfs_seamless` and `ecmwf_ifs025`, `temperature_2m_previous_dayN` |
| Training truth | Kalshi: NWS CLI daily high; Polymarket: daily max of METAR observations (routine + special, rounded to °F), both via IEM | each venue's own settlement basis |
| Scoring truth | each venue's own recorded result | not re-derived |

Kalshi's settlement source changed from the NWS CLI to The Weather Company
around 2026-08-14. Scores use Kalshi's result either way; the backtest reports
how often the CLI high falls in Kalshi's winning bucket.

## Windows

- **Train:** target dates 2024-01-01 to 2025-06-30. Model parameters are fit here only.
- **Test:** target dates 2025-07-01 to 2026-09-30. Scored once, with frozen parameters.
- **Forward:** target dates from 2026-10-01, scored the same way as data arrives.
- **Dev:** 2025-04-01 to 2025-06-30, a slice of the training window used only to
  debug the pipeline end to end before the test run. Its scores are in-sample and
  are never reported as results.

## Lead points and leakage

Scores are taken at fixed local clock times in the settlement station's time zone:

| Lead point | Forecast used | Latest model run that can feed it |
|---|---|---|
| D-1 12:00 | `previous_day2` | `previous_dayN` for hour h comes from a run issued at least 24·N h before h. The day-D max includes hour 23:00, so the latest run used was issued around D-2 23:00 local and published (GFS ~4 h, ECMWF ~6 h later) by about D-1 05:00 local, seven hours before the lead point. |
| D 08:00 | `previous_day1` | latest run issued around D-1 23:00 local, published by about D 05:00 local, three hours before the lead point. |

A market price is the latest snapshot **at or before** the lead time. Nothing
after the lead time is ever used. Backtest prices may be up to 12 hours older
than the lead time; live snapshots, taken hourly, up to 2 hours.

*Amended 2026-10-16, before any test-window scoring:* the first draft used a
2-hour limit everywhere. Debugging on the dev slice showed that Kalshi emits a
candle only for hours with activity, while the order book persists in between:
a market quoted 0.33/0.46 at 04:00 ET had no candle until 08:00. A standing quote
is still the price at the lead time, and the 2-hour limit was silently dropping
most early-morning New York and Miami ladders (14 of 87 scored at D 08:00).

## Model: det_gauss_v1

`high ~ Normal(mean(GFS, ECMWF) + bias[station, N], sigma[station, N])`, where the
forecast for each model is the max of its 24 hourly `previous_dayN` values for the
local day, both models must be present, and bias/sigma are the mean and standard
deviation of (observed high − forecast) over the training window, with the observed
high on each venue's settlement basis (see Data) (minimum 60 days;
sigma floored at 0.75 °F). Bucket probability integrates the Normal over the
bucket's reported-integer range (±0.5 °F).

The live `ens_kernel_v1` ensemble model has no archive and is scored forward only.

## Market probability

- **Kalshi:** the latest hourly candle at or before the lead time, then the mid of its
  closing YES bid and ask. If that candle has a missing side or a spread wider than
  $0.25, the bucket has no price; an older candle is never substituted. A side quoted
  at $0.00 (no bids) or $1.00 (no asks) counts as that price.
- **Polymarket:** the last CLOB price point whose hour has fully elapsed by the lead
  time (a point stamped t counts from t + 1 h).
- Prices across an event's ladder are divided by their sum (removes the overround).

## Inclusion

An event (city, date, venue) is scored at a lead point only if its buckets run from
an open-low to an open-high bucket with no gaps, every bucket has a model and a
market probability, exactly one bucket resolved YES, and both forecast models are
present. Events dropped for each reason are counted and reported.

## Scores

Per event, lower is better for all three:

- **Brier:** sum over buckets of (p − outcome)².
- **RPS:** ranked probability score over the ordered ladder.
- **Log score:** −ln p(winning bucket), with p floored at 0.001.

Results are reported per venue and lead point as means, with the model − market
difference and a 95% paired bootstrap interval that resamples events
(2,000 resamples; events sorted by key and seeded per lead point, so the interval
does not depend on database row order). Calibration is shown on bucket-level probabilities.
No per-city or per-month result is used to pick a headline.

## Amendments before test scoring (2026-10-16)

An independent review of the code against this protocol, and checks on the dev
slice (training data only), led to these changes. All were made before any
test-window score was computed, and the model was refit afterwards on the
training window only.

1. **Polymarket training truth.** Polymarket settles on station METAR observations,
   not the CLI report. On the dev slice, the METAR max fell in Polymarket's winning
   bucket on 72 of 72 days and the CLI high on 50 of 72. Fitting Polymarket's model
   to CLI highs would have biased it warm by the CLI-vs-METAR gap.
2. **Kalshi price rule order.** The draft code filtered out wide-spread candles and
   then took the latest remaining one, which could reach back to an older, staler
   price. The rule is now as-of first, then the price test.
3. **Polymarket timestamps.** A history point is treated as known only from the end
   of its hour, which can only make the market's price older, never newer.
4. **Ladder completeness.** Events whose stored buckets do not cover every outcome are
   dropped and counted, instead of being scored on a renormalized partial ladder.
5. **Deterministic intervals.** See Scores.

Results are written to `results/backtest_test.json` and rendered by
`wvm backtest report`.
