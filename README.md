# polymarket-bot

Maker-side quoting bot for Polymarket daily temperature markets, priced from
public weather-model ensembles (NWS/NDFD, GFS, ECMWF).

Strategy rationale: see [docs/research-report.md](docs/research-report.md).
TL;DR — liquidity is structurally undersupplied in low-probability weather
buckets; an informed maker collects wide spreads plus maker rebates by quoting
them from a real forecast model.

## Build phases (from the research report)

| Phase | Module | Status |
|-------|--------|--------|
| 0. Resolve US-access question (which platform, fees, legality) | — | **BLOCKING, unresolved** |
| 1. Read-only order book logging (~1 week) to measure real spreads/depth | `ingest/` | skeleton |
| 2. Forecast layer: ensembles → temperature-bucket probability distributions | `forecast/`, `model/` | skeleton |
| 3. Passive backtest: model probabilities vs logged prices, net of spread | `analysis/` | skeleton |
| 4. Paper-trade maker quoting (model price ± margin), measure fill quality | `strategy/`, `execution/` | skeleton |
| 5. Small-capital live pilot | `execution/` | not started |

## Layout

```
config/settings.yaml      # cities, polling cadence, quoting params
src/polybot/
  config.py               # settings + env loading
  clients/                # CLOB + Gamma API wrappers (read-only first)
  ingest/                 # order book snapshot logger
  forecast/               # NWS / GFS / ECMWF fetchers
  model/                  # bucket probability distributions
  analysis/               # edge measurement vs logged books
  strategy/               # maker quote generation
  execution/              # paper engine (live engine later)
  storage/                # sqlite persistence
  cli.py                  # entry points for each phase
```

## Usage (once implemented)

```bash
uv sync
polybot discover            # find active weather markets
polybot log-books           # phase 1: snapshot order books on a loop
polybot forecast            # phase 2: pull forecasts, build distributions
polybot edge-report         # phase 3: model vs market gap analysis
polybot quote --paper       # phase 4: paper maker
```

## Key constraints (verified in research)

- Hybrid CLOB: offchain matching, onchain settlement on Polygon (chain 137), EIP-712 signed orders.
- SDK: `py-clob-client` v2 (docs also recommend the newer `py-sdk` — evaluate at build time).
- Fees favor makers: makers pay zero on the international platform (V2, eff. 2026-03-30);
  Polymarket US pays a maker rebate (θ = −0.0125, eff. 2026-04-03).
- Do NOT build: arbitrage bots, copy-trading, crypto latency sniping (all ruled out).
