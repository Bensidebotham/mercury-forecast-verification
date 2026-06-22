# Mercury — Forecast vs. Market Verification Pipeline

**Can a calibrated weather model out-predict the betting market on daily city temperatures?**

Mercury is a read-only Python data pipeline that ingests daily high-temperature **markets** from
Kalshi and Polymarket plus multi-model weather **ensembles** (GFS + ECMWF via Open-Meteo, NWS, and
live METAR station observations), unifies them into one normalized store, and benchmarks the
**model-implied** probability against the **market-implied** probability for every market — scored
against the official **NWS settlement** with Brier score, log-loss, and calibration, segmented by lead
time. Results are published to a live dashboard.

> **No trading is performed anywhere in this repo.** The deliverable is the measurement and the honest
> result, not a strategy or a P&L. (Earlier trading experiments are parked in `legacy/`.)

**Live dashboard:** https://mercury-forecast-verification.vercel.app

---

## Data lineage

```
Kalshi /markets ............┐
Polymarket Gamma/CLOB ......┼─▶ pipeline/ingest ─▶ verify_db ─▶ analysis/verification ─▶ export ─▶ frontend/public/evaluations.json
Open-Meteo (GFS+ECMWF) .....┤      (run_once)      (vmarket /     (Brier / log-loss /     (Parquet      │
NWS + METAR (observations) .┘                       vquote /       calibration by          + JSON)       ▼
                                                    vpred)         lead time)                      Next.js dashboard (Vercel)
```

- **vmarket** — unified market registry across venues (`venue:external_id` key, bucket bounds, close time, settled outcome)
- **vquote** — market-implied probability snapshots over time
- **vpred** — model-implied probability snapshots over time (with lead-hours)

Scoring pairs, for each settled market and target lead time, the model and market snapshots nearest
that lead time with the realized outcome. Backfilling Kalshi's settlement history seeds outcomes
immediately; live model-vs-market lead-time comparisons accrue forward as snapshotted markets settle.

## Quickstart

```bash
uv sync
uv run polybot backfill-kalshi   # seed settled markets (no auth needed)
uv run polybot ingest-once       # one read-only ingestion cycle (model + market snapshots)
uv run polybot verify-report     # model vs. market Brier/log-loss by lead time
uv run polybot export            # write data/evaluations.{parquet,json}

# dashboard
cp data/evaluations.json frontend/public/evaluations.json
cd frontend && npm install && npm run dev   # / = live state, /?sample=1 = illustrative sample
```

Scheduled ingestion runs via GitHub Actions (`.github/workflows/ingest.yml`, every 3h) and republishes
`frontend/public/evaluations.json`, which the deployed dashboard reads.

## Layout

```
src/polybot/
  clients/kalshi.py        keyless Kalshi temperature-market client
  clients/gamma.py         Polymarket market discovery (existing)
  forecast/                Open-Meteo ensemble, NWS, METAR observations (existing)
  model/buckets.py         bucket probability from ensemble members (existing)
  model/kalshi_buckets.py  parse Kalshi strike labels
  storage/verify_db.py     unified cross-venue SQLite store
  pipeline/ingest.py       one read-only ingestion cycle
  pipeline/backfill.py     Kalshi settlement-history backfill
  pipeline/export.py       Parquet + JSON export
  analysis/verification.py Brier / log-loss / calibration, model vs. market by lead time
frontend/                  Next.js + Recharts dashboard
legacy/                    parked trading experiments (not part of the pipeline)
```

## Tests

`uv run pytest tests/ -q` — 33 passing (pure scoring/parsing/storage logic + ingestion binding).

## Honest evaluation

See [docs/EVALUATION.md](docs/EVALUATION.md) for the current sample size, the model-vs-market numbers,
and the caveats. The finding is reported plainly whichever way it falls.
