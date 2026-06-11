# Polymarket Bot Strategy Research Report
*Generated 2026-06-10 — deep-research workflow, 24 sources, 25 claims adversarially verified (18 confirmed, 7 refuted)*

## TL;DR

The weather trades you saw are real, and the mechanism is now reasonably clear: the edge is **not** that longshots are systematically mispriced "free money" — it's that **almost nobody wants to quote low-probability weather buckets** (market makers face bounded upside / asymmetric downside there), so the few traders who price those buckets off actual forecast models (NWS/ECMWF/GFS) get paid well for it. The recommended strategy: **maker-side quoting in daily temperature markets, priced from public weather-model ensembles**, on a small-capital pilot first.

---

## 1. The weather longshot mystery — what's actually happening

Your hypothesis was right: it's "certain factors were met and flagged the trade as profitable," not luck.

- **Verified (3-0):** The best microstructure research (Dubach, arXiv 2604.24366, May 2026) attributes the longshot premium to a *liquidity-provision constraint* — market makers avoid quoting low-probability binaries because the payoff is asymmetric against them. This means cheap longshots are NOT systematically underpriced by dumb money; blind buying of sub-1¢ outcomes has no verified edge.
- **Verified (3-0):** Weather/temperature markets are active (~$16M cumulative volume, ~$1.7M in daily temperature markets), Polymarket runs an official weather profit leaderboard, and low-priced buckets do produce multi-x moves (a Denver temperature bucket moved +746% intraday, verified live).
- **Corroborated but NOT verified:** Weather specialists like `gopfan2` (~$2M+ claimed net) reportedly buy Yes below $0.15 using "temperature laddering" — spreading entries across adjacent temperature buckets as forecast models update. The profit figures come from blogs (polymarketweather.com, Medium write-ups), not independent verification.
- **The implied mechanism:** hourly-updating forecast ensembles (NWS/NDFD, ECMWF, GFS) move faster than the quotes in thin weather books. When the models shift probability into a bucket still priced at 1-5¢, the trade looks like a "<1% miracle" from outside but is actually a model-vs-stale-price edge — exactly the shape of your PropEdge/Kalshi work.

## 2. What's ruled OUT (this is the most valuable part)

- **Arbitrage is dead at meaningful capital — high confidence (multiple 3-0 votes).** A UCLA study (arXiv 2605.00864) of 75M order-book snapshots across 173 NBA games / 3,042 markets found: single-market arb appeared **7 times total** with ~3.6s median duration; combinatorial arb (moneyline vs spread) totaled **$559.59** of extractable profit, with 76.9% of opportunities capped at ~14.8 shares of depth. Markets were arbitrageable 0.18% of in-game time. Don't build an arb bot.
- **Copying top traders doesn't translate to a bot.** The famous ~$85M Trump win (French trader "Théo," ~$80M staked across 11 accounts) was a discretionary conviction bet powered by privately commissioned YouGov "neighbor polls" — an information edge, not automation. Claims about leaderboard win-rate distributions failed verification.
- **Latency/news-sniping in crypto markets:** Polymarket's new dynamic fees were introduced partly to kill latency arbitrage in short-term crypto markets. Crowded and now fee-penalized.

## 3. Why the maker-side weather strategy is the recommendation

1. **You get paid to quote.** Fees changed in March–April 2026 and now actively favor makers (all verified 3-0 against official docs):
   - International platform (Fee Structure V2, eff. 2026-03-30): taker fees by category (crypto 0.07, sports 0.03, economics/weather 0.05); **makers never charged**; 20-25% of taker fees redistributed to makers daily.
   - Polymarket US (eff. 2026-04-03): parabolic fee `Fee = θ × C × p × (1−p)`, taker θ = 0.05 (max $1.25 per 100 contracts at p=0.50), **maker rebate θ = −0.0125** (25% of taker fees, paid at trade time).
2. **The verified "longshot premium = maker constraint" finding cuts in your favor as a maker.** The academic literature says liquidity is undersupplied in tail buckets — an informed maker collects both the wide spread and the rebate for supplying it.
3. **Daily objective resolution.** Temperature markets resolve against station data, sidestepping most UMA governance risk (disputed resolutions take 4-6 days and escalate to a token-holder vote — real tail risk in subjective markets).
4. **It's your existing skill set.** Forecast model vs. market price is structurally identical to PropEdge's fair-line-vs-odds approach, and Kalshi weather markets give you a cross-platform sanity check or hedge.

## 4. Practical/API facts (all verified against official docs 2026-06-10)

- Hybrid CLOB: offchain matching, atomic onchain settlement on Polygon (chain 137), non-custodial, EIP-712 signed orders.
- Official Python SDK: `py-clob-client-v2` (docs now also recommend newer `py-sdk` for new projects). Auth is two-level: one-time L1 wallet signature derives L2 API key/secret/passphrase, then HMAC-SHA256 per request. Each order still requires local EIP-712 signing.
- Liquidity is extremely concentrated: ~505 contracts >$10M carry 47% of all volume; ~156k mid-tier contracts carry 7.5%. The long tail is near-dead — weather books are thin, which caps position size but is also *why* the maker niche exists.

## 5. Open questions to resolve before/while building

1. **US access (material gap):** Can a US resident legally run a bot on Polymarket US (CFTC-regulated) vs the international CLOB? Which platform hosts the liquid weather markets? Fee schedules differ between them. No claim on this survived verification — needs first-hand checking against your actual account type.
2. **Real execution costs on sub-10¢ contracts:** the one spread-magnitude claim (1,300-1,800 bps half-spreads below $0.10) FAILED verification — measure it live from the order book before sizing anything.
3. **How crowded is the niche:** Feb 2026 blog write-ups describe existing weather bots ("quietly making $24,000"); capacity may be limited.
4. **Realized profitability of weather specialists:** on-chain trade reconstruction of accounts like gopfan2 would answer this definitively and is doable with public Polygon data.

## 6. Suggested build path

1. Connect via `py-clob-client-v2` with read-only market data; pull weather market order books and log spreads/depth for ~1 week (answers open question #2 for free).
2. Build the forecast layer: NWS/NDFD point forecasts + GFS/ECMWF ensemble spread → probability distribution over temperature buckets per city per day (same shape as your PropEdge quantile models).
3. Backtest passively: compare your model probabilities to logged market prices; only proceed if persistent gaps exist after spread costs.
4. Pilot with small capital as a maker (post limit orders inside the spread at your model price ± margin), collect rebates, measure fill quality.
5. Only then consider the taker-side longshot entries when model probability >> market price.

## Refuted claims (do not rely on these if you see them elsewhere)

- "Polymarket is zero-fee" — no longer true as of March/April 2026 (0-3).
- Specific leaderboard win-rate stats ($9.55M top trader at 53.7% win rate; top-50 clustering near 50%) (0-3 / 1-2).
- "63% of short-cycle markets are dormant" and the $450k long-duration liquidity figures (0-3 / 1-2).
- "$750 UMA proposal bond / fully permissionless resolution" (1-2).
- The 1,300-1,800 bps sub-$0.10 spread figure (1-2).

## Key sources

- arXiv 2604.24366 (Dubach, May 2026) — market microstructure, longshot premium
- arXiv 2605.00864 (UCLA, Apr 2026) — NBA arbitrage study
- docs.polymarket.com/trading/fees + docs.polymarket.us/fees — fee schedules (live-verified)
- docs.polymarket.com (trading overview, CLOB auth, resolution) — API (live-verified)
- polymarket.com/leaderboard/weather/all/profit — official weather leaderboard
- thefp.com — Théo/$85M Trump bet reporting
- polymarketweather.com, Medium, dev.to write-ups — weather specialist corroboration (unverified)
