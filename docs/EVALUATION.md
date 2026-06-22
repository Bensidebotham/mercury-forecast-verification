# Evaluation — Model vs. Market

> Honest status. Updated as the pipeline accrues data. Run `uv run polybot verify-report` for the
> current numbers and paste the table here.

## Current state (initial run, 2026-06-22)

- **Settled markets backfilled from Kalshi:** 538 (across NY, LA, Chicago, Miami, Austin daily-high series)
- **Model + market snapshots captured on open markets (first cycle):** 89 paired snapshots
- **Resolved markets with paired snapshots (scoreable):** 0 — *expected on day one.*

Why 0 scoreable at launch: the comparison needs **both** a forward snapshot of the model/market
probability **and** the realized outcome. Backfill gives outcomes (538 settled markets) but no
historical order books, so those can't be scored against the model retrospectively. The 89 snapshots
just captured are on markets that are still **open**; they become scoreable once they settle (Kalshi
daily-temperature markets settle the next morning on the NWS CLI report) and the next `backfill-kalshi`
run marks them settled. So the model-vs-market comparison **populates within ~24–48h of the scheduler
running**, and grows daily thereafter.

## Model vs. market (Brier / log-loss by lead time)

_Populate from `uv run polybot verify-report` once resolved+paired markets exist:_

| lead (h before close) | n | model Brier | market Brier | model logloss | market logloss |
|---|---|---|---|---|---|
| 72 | — | — | — | — | — |
| 48 | — | — | — | — | — |
| 24 | — | — | — | — | — |
| 6  | — | — | — | — | — |

Lower Brier / log-loss = better. Read the result plainly — including "the market is more accurate at
short lead times" if that's what the data shows.

## Caveats

- **Sample size:** starts at 0 scoreable and accrues ~tens of markets/day. Early numbers are noisy;
  the calibration story needs a few weeks of accrual to be meaningful.
- **Snapshot nearest-match:** each settled market is scored against the model/market snapshot **nearest**
  the target lead time, not exactly at it. With ingestion every 3h, snapshots are within ~1.5h of target.
- **No historical order books:** backfilled settled markets contribute outcome coverage only; they are
  not scored against the model (we lack the market's historical implied probability for them).
- **Settlement source:** Kalshi temperature markets settle on the official NWS CLI daily maximum, which
  is the same observation source the model debiases toward — outcomes are well defined and consistent.
- **Known inefficiency:** `ingest-once` currently recomputes the ensemble per bucket within a city/date
  rather than caching it per city/date — fine for a 3-hourly cron, but a caching pass would cut redundant
  Open-Meteo calls before tightening the schedule.
