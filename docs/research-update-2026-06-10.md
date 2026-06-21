# Research Update — Deep Research Round 2 + Live Measurements
*2026-06-10. Supplements `research-report.md`. Sources: deep-research workflow (22 sources fetched, 94 claims extracted, 25 adversarially verified → 18 confirmed / 7 killed) + live Gamma/CLOB/data-api pulls made today.*

## Confirmed findings (high confidence, 3-0 verification votes unless noted)

### Weather specialists are real, profitable, and include bots
- **gopfan2: $355,054 all-time profit on $4.6M volume (~7.7% margin)** — verified to the dollar against the official weather leaderboard API on 2026-06-10. All top-20 weather traders are positive (rank 20 still >$50k).
- Margin dispersion implies distinct strategies: gopfan2's high-margin/low-turnover profile fits selective taker longshot/ladder entries; **ColdMath (~1.25% on $10.9M)** and **Poligarch (~0.73% on $9.9M)** fit maker-style quoting. (Attribution is inference, not order-flow reconstruction.)
- Weather leaderboard **rank 11 is literally named "automatedAItradingbot"** ($50–65k profit) — the niche has bots and they're profitable, but the "14 of top 20 leaderboard wallets are bots" claim was REFUTED (1-2); crowding remains unquantified.

### Live spread measurements (mine, today — Seoul Jun-11 books)
| Bucket | Mid | Spread | % of mid | Touch depth |
|---|---|---|---|---|
| center (~0.475) | 0.475 | 1¢ | 2.1% | ~34 |
| shoulder (~0.145) | 0.145 | 1¢ | 6.9% | ~24 |
| tail (~0.06) | 0.06 | 1.3¢ | 21.5% | ~78 |
| deep tail (~0.0035) | 0.0035 | 0.1¢ | 28.6% | ~2,220 |
| deepest (~0.0015) | 0.0015 | 0.1¢ | 66.7% | ~963 |

Consistent with Dubach's panel finding (1,300–1,800 bps spreads below 0.10). Six+ cities active daily, $40k–$250k 24h volume per event, tail buckets quoted at 0.0005.

### The Dubach mechanism is weaker than previously framed
The paper documents the longshot **spread premium** but **explicitly does not establish** the liquidity-provision (inventory-risk) mechanism over behavioral mispricing — it lacks maker inventory/time-on-book data. Practical impact: none for a maker (the wide spread is revenue either way); for takers it means the "structural mispricing" story is less certain — model edge must be proven, not assumed.

### Maker bots are officially sanctioned and subsidized
- Polymarket's market-maker docs direct automated makers to the CLOB REST API + WebSocket feeds. No anti-bot policy on the CLOB (restrictions are jurisdictional).
- **Liquidity Rewards program**: daily payments to resting limit orders, >$5M distributed in April 2026, $1M program at CLOB V2 launch. Scoring `S(v,s)=((v-s)/v)²·b` rewards tight two-sided quoting; **single-sided orders penalized ÷3 and disallowed outside 0.10–0.90 midpoints** → rewards accrue on center/shoulder buckets, not tails. Tail quoting earns spread only.
- Fees (verified against docs.polymarket.com): makers pay zero; Weather taker feeRate 0.05 with 25% maker rebate; only geopolitical markets remain fee-free. The marketmath.io fee-curve parameters (Weather 0.025/0.5 exponent model, flat 0.10% US taker fee) were REFUTED 0-3 — pull exact math from docs.polymarket.com/trading/fees only.

### CLOB V2 is a hard implementation constraint
**April 28, 2026: CLOB V2 live, no V1 compatibility.** New Exchange contracts, **pUSD replaces USDC.e as collateral**, revised order struct (nonce/feeRateBps/taker removed; timestamp/metadata/builder added). V1 SDKs and V1-signed orders are dead. Any client code must target V2; check `py-clob-client`/`py-sdk` V2 support before building on them.

### Don't make an LLM the trader
- Best frontier model (GPT-5) returned **0.943 vs 1.0 break-even** betting against prediction-market prices on 1,367 Kalshi events; all five models tested were net losers. PolyBench: 5/7 frontier LLMs lost money live on Polymarket, alpha decaying with size.
- Unconstrained LLM agent backtests: **−2.77% with 36% max drawdown via overtrading**, while a fee-aware classical strategy stayed positive (+1.67%, 3.2% DD).
- LLM priors beat markets only at long horizons; markets aggregate breaking news faster near resolution → never take positions near resolution on stale model knowledge. (Observation lock-in is the inverse case — there *we* have the faster data feed.)
- Continuous-learning loop must track **calibration and drift separately from hit rate** (narrative/temporal/confidence drift all documented in live evaluation; medium confidence, single vendor preprint).

### US access (high confidence)
- International polymarket.com **geoblocks US IPs and rejects orders at the API level** (33 countries fully restricted).
- **Polymarket US** (polymarket.us): CFTC-regulated (QCX LLC = DCM, QC Clearing = DCO), launched Dec 3 2025, full developer API (REST + WS, official Python/TS SDKs, Ed25519 signing) behind KYC (SSN + photo ID). API requires key even for market data (probed today).
- **Unresolved and decisive:** no claim survived verification on whether Polymarket US lists the liquid daily-temperature markets. The gopfan2 leaderboard lives on the international platform. Secondary sources (bettingusa.com, June 2026) call **Kalshi "the clear leader in the weather category"** for US residents, with granular daily high/low city markets.

## Refuted this round (do not rely on)
- marketmath.io per-category fee curve + flat 0.10% US taker fee (0-3)
- "14 of top 20 leaderboard wallets are bots" (1-2)
- Kalshi maker fee = 1.75%·p·(1−p) formula (1-2 — treat Kalshi maker fee math as unverified; pull the official PDF)
- Polymarket US API endpoint counts/rate limits from blogs (0-3)

## Open questions (carried forward)
1. Does Polymarket US list weather markets with real liquidity? → **Answer empirically: KYC onboard, pull the market list via authenticated API.** This decides the venue.
2. Niche crowding/edge decay since gopfan2's profits accumulated — unquantified.
3. Exact Weather taker-fee math under post-Mar-31 share-based calculation at sub-0.05 prices: does the fee or the 650–900 bps half-spread dominate longshot entry cost?
4. gopfan2 on-chain reconstruction (address 0xf2f6…5817 public): entry timing vs forecast-ensemble shifts — the key signal question. Doable with Polygon data.

## Strategy ranking after this round (changes from initial list in bold)
1. **Observation lock-in sniping** — unchanged, build first; it's the inverse of the documented LLM failure mode (we have faster data than the market near resolution).
2. **Maker quoting** — **strengthened**: officially sanctioned, subsidized (rewards + rebates + zero fees), and the two confirmed high-volume weather profiles look like makers. **Design note: liquidity rewards only pay within 0.10–0.90, so quote center buckets for rewards and tails for spread.**
3. **Forecast-ensemble taker longshots** — **demoted slightly**: mechanism less verified than assumed, and 650–900 bps half-spreads are the real entry cost; requires proven calibration before real money.
4. Sports fair-value, futures value, theta farming, cross-platform RV — unchanged as later supplements.

## Venue decision tree (US resident)
- **Path A (preferred if weather exists there):** KYC on polymarket.us → verify weather market list + books via API → build on US API (Ed25519, separate SDK).
- **Path B (fallback, likely):** daily-temp niche is intl-only → run the identical strategy stack on **Kalshi** weather series (KXHIGH*) — CFTC-regulated, granular daily city markets, WS guide already reviewed in `kalshi-ws-guide-review.md`. Forecast layer is venue-agnostic by design.
- **Not a path:** trading the international CLOB from the US (geoblocked at API level; circumvention = account/funds risk).

## RESOLVED 2026-06-10 (evening): Path A confirmed — verified against docs.polymarket.us
Ben already has a Polymarket US account. Verified directly from official US docs:

- **Temperature Contracts exist on Polymarket US** for 5 cities: NYC (KNYC Central Park), SF (KSFO), Miami (KMIA), Chicago (KMDW), LA (KLAX). Settled against the official **NWS Daily Climate Report (CLI)** per city, at 8:00 AM ET the following day; CLI-vs-METAR inconsistencies delay settlement to 11:00 AM ET for review. (Source: docs.polymarket.us/faqs/weather-faqs)
  - The CLI/METAR sources are public NWS feeds → exactly what observation lock-in (#3) and the forecast layer need. Settlement stations are now pinned per city.
- **Fee schedule (eff. Apr 3, 2026):** `Fee = Θ × C × p × (1−p)`; taker Θ=0.05 (max $1.25/100-lot at p=0.50), **maker rebate Θ=−0.0125 paid at trade time**. At p=$0.01: taker pays $0.05 per 100-lot, maker *receives* $0.01. Tail-bucket fees are negligible; maker side is rebate-positive at all prices. (Source: docs.polymarket.us/fees)
- **Liquidity Incentive Program (updated June 1, 2026):** Exchange scores resting orders **every second** by price/size proximity to best price; rewards split pro-rata. **"Climate, Macro, Politics, and Culture each earn $1,000/day per event"**, all events in those categories eligible by default. With 5 daily temperature events, that's up to ~$5k/day in Climate reward pools split among makers — a direct subsidy for maker quoting (#2). Key params per program: discount factor (distance penalty) and target size (min contracts per side to qualify). (Source: docs.polymarket.us/incentives/liquidity)
- **API:** REST + WebSockets + official Python/TS SDKs (`polymarket-us` package; key ID + secret auth). All market-data endpoints require an API key (verified empirically — no anonymous access). Institutional API + FIX also exist. Incentive-programs endpoint is public.
- polymarket.us website is a signup landing page only; product is app-first. Bot development is API-only — fine.

**Decision: build on Polymarket US.** Next steps: (1) Ben generates an API key from his account; (2) retarget `clients/` to docs.polymarket.us REST/WS (Ed25519/key auth, `polymarket-us` Python SDK); (3) Phase 1 logging on the 5 cities' temperature events; (4) NWS CLI/METAR ingest for the settlement stations above.
