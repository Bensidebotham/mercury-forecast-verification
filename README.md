# polymarket-bot

Paper-trading bot for Polymarket daily temperature markets, priced from public
weather-model ensembles (open-meteo GFS+ECMWF members, debiased toward NWS
point forecasts) with live station observations as a lock-in signal.

Strategy rationale: [docs/research-report.md](docs/research-report.md) and
[docs/research-update-2026-06-10.md](docs/research-update-2026-06-10.md).
TL;DR — liquidity is structurally undersupplied in low-probability weather
buckets; an informed maker collects wide spreads plus maker rebates (and on
Polymarket US, $1,000/day/event Climate liquidity rewards) by quoting them from
a real forecast model.

**Venue:** Polymarket US (CFTC-regulated; lists temperature markets for NYC,
SF, Miami, Chicago, LA — settled on NWS CLI reports). Paper trading currently
runs against the public *international* Gamma/CLOB feeds (same market
structure, no auth needed); the US API client slots in once an API key exists.

## Status

| Piece | State |
|-------|-------|
| Market discovery (Gamma, 5 cities, bucket parsing) | **working** |
| Forecast layer (open-meteo ensembles + NWS debias + METAR obs) | **working** |
| Bucket probability model (kernel mixture, obs truncation, locked days) | **working, tested** |
| Taker signals + maker quotes (US fee curve, exposure caps) | **working, tested** |
| Paper engine (simulated fills, settlements, PnL, calibration log) | **working, tested** |
| Live trading | **does not exist** (deliberately; gated on paper results) |
| Market-making strategy (`strategy/market_maker.py`) | **sketched + tested** — see `docs/market-making-design.md` |

## Usage

```bash
uv sync
uv run polybot discover              # list active temperature bucket markets
uv run polybot forecast --city NY    # model vs market, one city
uv run polybot paper-run             # the loop: forecast -> signals -> paper fills
uv run polybot paper-run --cycles 5  # bounded run
uv run polybot log-books             # snapshot-only mode (no trading sim)
uv run polybot report                # PnL, fills, measured spreads, calibration
uv run polybot dashboard             # live web UI at http://127.0.0.1:8787
uv run pytest                        # 22 tests
```

Long-running setup (both survive closing the terminal):

```bash
nohup uv run polybot paper-run  >> data/paper-run.log  2>&1 &
nohup uv run polybot dashboard  >> data/dashboard.log  2>&1 &
# stop them later with: pkill -f "polybot (paper-run|dashboard)"
```

Run `paper-run` continuously (tmux/launchd) and check `report` daily. The
calibration table (model prob vs settled outcomes) is the go/no-go gate for
real money — target: several weeks of settlements with honest bins before
funding anything.

## Layout

```
config/settings.yaml      # cities/stations, model params, caps, fee thetas
src/polybot/
  config.py               # typed settings
  clients/gamma.py        # market discovery (public, intl)
  clients/clob.py         # order books (public, read-only)
  forecast/ensemble.py    # open-meteo GFS+ECMWF members
  forecast/nws.py         # NWS point forecast (debias anchor)
  forecast/obs.py         # METAR running max + day-locked logic
  model/buckets.py        # bucket parsing + probability model
  strategy/signals.py     # taker entries net of US fees
  strategy/maker.py       # two-sided quotes around model price
  execution/paper.py      # simulated fills, settlements, positions
  engine.py               # the cycle loop
  analysis/edge.py        # PnL / spread / calibration reports
  storage/db.py           # sqlite
tests/                    # model, strategy, paper-engine tests
```

## Known model gaps (paper trading exists to measure these)

- Hourly METAR maxima undershoot the official CLI daily max by ~1–2°F
  (buffered/biased in config; learn the per-station correction from
  settlements).
- Coastal stations (KSFO, KLAX) run cooler than ensemble gridpoints; NWS
  blend helps, but the marine-layer error will show up in calibration.
- Maker fill simulation is optimistic about queue position (haircut applied);
  real fill quality needs the live pilot to measure.

## Next steps

1. Accumulate paper settlements; tune `obs_buffer_f`/`locked_bias_f`/sigma
   from the calibration report.
2. Polymarket US API client (needs API key from the account) — same interface
   as `clients/gamma.py`/`clob.py`, swaps in for the live pilot.
3. Per-station bias correction from logged forecast-vs-CLI pairs.
4. Live pilot ($100, lock-in trades first) only after calibration passes.
