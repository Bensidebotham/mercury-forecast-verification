# Review: "Kalshi WebSocket API – Pro Football Market Monitoring Guide"

*Reviewed 2026-06-10 against the live Kalshi API changelog and fee schedule.
Source file: `~/Downloads/Kalshi WebSocket API – Pro Football Market Monitoring Guide.txt` (dated Oct 2025).*

## Verdict

The guide is a solid, mostly-accurate piece of **plumbing documentation** — auth,
channels, subscribe/unsubscribe mechanics, reconnect strategy are all correct in
shape. Two problems:

1. **It's 8 months stale and the API has moved.** The biggest break: Kalshi
   removed the legacy integer price/count fields in **March 2026**. Every example
   payload in the guide (`price: 96`, `delta: -54`, `yes_price: 36`, `count: 136`)
   uses fields that may no longer be sent — current messages use `_fp`
   (fixed-point) and `_dollars` equivalents. Code written verbatim against the
   guide's schemas would parse nothing. Verify current schemas at
   docs.kalshi.com before writing deserializers.
2. **It contains zero strategy content.** It tells you how to *watch* markets,
   not how to make money in them. There is no order placement, no fee math, no
   edge model, no risk sizing. Monitoring infra is the easy 20%.

## Section-by-section accuracy

| Guide section | Status | Notes |
|---|---|---|
| §1 Auth (RSA-PSS, `KALSHI-ACCESS-*` headers, sign `ts+GET+/trade-api/ws/v2`) | ✅ Still correct | One addition: API keys now support **read/write scopes** (Dec 2025). Use a read-only key for the logging phase. |
| §2 Channels (ticker, trade, orderbook_delta, market_lifecycle_v2) | ✅ Correct set | Since publication: `ticker` now includes L1 book sizes (Feb 2026); `market_lifecycle_v2` emits `metadata_updated` and excludes MVE tickers; new `user_orders` channel (Feb 2026) is better than `fill` alone once trading. |
| §2.2/§4 message field examples | ⚠️ **Outdated** | Legacy integer fields removed Mar 12, 2026 → `_fp` / `_dollars`. Also `tick_size` removed May 2026 → `price_level_structure` / `price_ranges` (sub-penny levels exist; book model must handle them). |
| §3 subscribe / update_subscription / unsubscribe, sid/seq semantics | ✅ Correct | |
| §5 Reconnect/backoff/resync advice | ✅ Good advice | Improvement: `orderbook_delta` now supports a `get_snapshot` action (Apr 2026) — on a seq gap you can request a fresh snapshot without tearing down the subscription. |
| §7 Rate limits ("20 reads/sec Basic", 200 connections) | ⚠️ Partially stale | 200-connection limit stands, but REST limits moved to a **token-cost model** with separate read/write budgets (Apr 2026), and API tiers are now auto-granted from trading volume (Jun 2026). Legacy `/portfolio/orders` endpoints cost 10× the V2 ones. |
| §8 Rust implementation advice | 🤨 Question the premise | See "Don't write this in Rust" below. |
| Python snippet (`extra_headers=`) | ⚠️ Breaks on current lib | `websockets` ≥ v14 renamed it `additional_headers`. |

Also worth knowing: the guide's dithering about `dollar_volume` units is moot
now — the `_dollars` fields are explicit. And `market` order type was deprecated
(Sep 2025); when the bot eventually trades, it's limit orders only — which is
fine, a maker bot only uses limit orders anyway.

## The fee math the guide omits (this is what decides profitability)

Verified against the Feb 2026 fee schedule:

- **Taker:** `7% × p × (1−p)` per contract (peaks at $0.0175 at p=0.50).
- **Maker:** Kalshi now charges makers too — roughly `1.75% × p × (1−p)`,
  charged only on fill. This is the opposite of Polymarket US, which *pays*
  a maker rebate (θ = −0.0125).
- **Special events** (NFL championship, elections): flat 0.25% maker fee.
- The parabolic shape means fees are near-zero on tail buckets: at p=0.05 a
  maker pays ~$0.0008/contract — negligible. At mid-prices (sports moneylines
  hover near 0.50) fees are at their maximum. **Fee structure itself favors
  tail-bucket weather quoting over midpoint football quoting.**

(Exact maker rates per series are in `kalshi.com/docs/kalshi-fee-schedule.pdf` —
re-verify before going live; the PDF was rate-limited during this review and the
maker formula above comes from secondary sources.)

## Strategic comments

**1. Pro Football is the wrong target, and the guide accidentally proves it.**
Its own trade example — `HIGHNY-22DEC23-B53.5` — is a *NYC daily high
temperature market*. The WebSocket machinery in this guide is category-agnostic;
nothing about it is football-specific except the ticker list you subscribe to.

Why football is a poor first market:
- NFL game markets are Kalshi's most liquid and most efficiently priced; the
  free fair-value reference (sportsbook lines) is available to every participant.
- In-play trading is dominated by firms with low-latency official data feeds.
  A background bot on a home connection loses every speed race.
- It is June. The NFL season starts in September. A "runs in the background
  and makes money" bot needs markets that resolve daily, year-round.

**2. Kalshi itself is the right call — it resolves the repo's blocker.**
The repo's Phase 0 ("US access question — BLOCKING, unresolved") is answered by
Kalshi: CFTC-regulated, unambiguously legal for a US resident to trade via API.
That alone justifies retargeting the project from Polymarket to Kalshi.

**3. The repo's verified strategy ports almost unchanged.**
The deep-research report's core finding — liquidity is structurally undersupplied
in low-probability weather buckets, so an informed maker quoting from real
forecast ensembles gets paid the spread — applies to Kalshi's weather series
(`KXHIGHNY`, `KXHIGHCHI`, etc.) just as it does to Polymarket's. Only the
`clients/` and `ingest/` layers change; `forecast/`, `model/`, `analysis/`,
`strategy/` are platform-agnostic. The fee headwind (maker fee vs Polymarket's
rebate) is real but tiny at tail prices, and is the price of legal certainty.

**4. Don't write this in Rust.**
The guide assumes a Rust implementation. The repo is Python, the edge is
model-vs-stale-price (hours timescale), not latency (milliseconds), and Python's
`asyncio` + `websockets` handles Kalshi's weather-market message volume without
breaking a sweat. Rewriting auth/signing/reconnect logic in Rust buys nothing
and costs weeks.

## Recommended plan (revised phases)

1. **Retarget Phase 0 → done:** platform = Kalshi (US-legal). Demo env
   (`demo-api.kalshi.co`) for all development.
2. **Phase 1 (logging):** read-only scoped API key; one WS connection;
   `market_lifecycle_v2` (global) for discovery + `orderbook_delta` on
   discovered `KXHIGH*`/`KXLOW*` weather tickers; persist snapshots+deltas to
   sqlite. Verify current `_fp`/`_dollars` message schemas empirically on day one.
   Run ~1 week to measure real spreads/depth in tail buckets.
3. **Phase 2 (forecast):** unchanged from repo plan — NWS/NDFD + GFS/ECMWF
   ensembles → bucket probability distributions per city/day.
4. **Phase 3 (passive backtest):** model probability vs logged book, net of
   spread *and* the maker fee formula above. Proceed only if persistent gaps survive.
5. **Phase 4 (paper maker), Phase 5 (small live pilot):** as in repo plan.
6. **Optional later:** dual-platform — same forecast model quoting whichever of
   Kalshi / Polymarket US has better economics per bucket; cross-platform price
   divergence is also a free sanity check on the model.
7. **Football, if ever:** revisit in August as *pregame* model-vs-line (slow
   edge), never in-play.

## Expectation setting

"Profitable bot running in the background" has a realistic shape: weeks of
logging and backtesting before any live order, position sizes capped by thin
tail-bucket books (that thinness *is* the edge), and modest absolute P&L at
pilot capital. The guide gets you the plumbing; the repo's forecast model is
the actual money-maker. The plumbing should take days, not weeks — spend the
time on the model and on measuring real fill quality.
