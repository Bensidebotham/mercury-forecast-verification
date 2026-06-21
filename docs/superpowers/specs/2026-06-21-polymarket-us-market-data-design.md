# Polymarket US live market data for paper trading — design

**Date:** 2026-06-21
**Status:** Approved (data source: Polymarket US, international kept behind a flag; REST polling)

## Goal

Paper-trade against **Polymarket US** market data — the venue we will trade live
— instead of the international public API, so paper results are representative.
Add US discovery / order-book / resolution reads normalized to the shapes the
PaperEngine already consumes, and let a config flag select the data source.

## What the live API looks like (verified 2026-06-21)

All on host `https://gateway.polymarket.us`, **all requests Ed25519-signed**
(anonymous access is unreliable — intermittently 401 "Missing required API key
headers"). Reuse the signing from `PolymarketUS`.

- **Discovery:** `GET /v1/search?query=temperature&limit=N` → `{events: [...]}`.
  Events have `category: "climate"`, `slug` like `temp-sfohigh-2026-06-21`,
  `title` "Highest temperature in San Francisco on June 21?", `endDate`,
  `volume`, `active`, `closed`, and a `markets` array of 6 bucket sub-markets.
  Cities map by airport-ish code in the slug: sfo→San Francisco, lax→LA,
  mdw→Chicago, nyc→NYC, mia→Miami. The event title still matches the existing
  `gamma._EVENT_RE` ("Highest temperature in (city) on (Mon D)?").
- **Bucket market:** `slug` like `tc-temp-sfohigh-2026-06-21-lt65f`,
  `outcomes` `["Yes","No"]`, `outcomePrices`, `orderPriceMinTickSize` 0.01,
  `minimumTradeQty`, `closed`, `active`. The bucket bound is in `title` /
  `titleShort`: `"64 or below"`, `"65 to 66"`, … `"73 or above"` (NOT in
  `question`, which is the event title, shared across all 6 buckets).
- **Order book:** `GET /v1/markets/{slug}/book` →
  `{marketData: {bids:[{px:{value},qty}], offers:[{px:{value},qty}]}}`.
- **BBO:** `GET /v1/markets/{slug}/bbo` → bestBid/bestAsk/settlementPx/etc.
- **Settlement:** `GET /v1/markets/{slug}/settlement` → 404 until resolved,
  then a settlement px (0/1).

## Engine contract to satisfy (unchanged)

The PaperEngine consumes exactly three operations today:
1. `gamma.find_weather_markets(cities, limit)` → rows
   `{token_id, event_slug, city, target_date, question, outcome_prices,
   end_ts, closed}` (engine then parses bucket bounds via
   `buckets.parse_bucket(question)`).
2. `clob.get_order_book(token_id)` → `{bids, asks, best_bid, best_ask,
   bid_depth, ask_depth}` or None.
3. `gamma.get_event_resolutions(slugs)` → `{token_id: 1|0|None}`.

We satisfy the same three with US data, using the bucket **slug** as the
engine's opaque `token_id` (it is the book-lookup key, like the CLOB token id).

## Design

### 1. `model/buckets.py` — `parse_us_bucket(label)`

New parser for the US label format, returning `(lo, hi, unit)` like
`parse_bucket`, unit always `"F"`:
- `"(\d+) or below"` → `(None, N)`
- `"(\d+) or above"` → `(N, None)`
- `"(\d+) to (\d+)"`  → `(lo, hi)`

### 2. `clients/us.py` — data methods on `PolymarketUS`

Give the client a `gateway_url` (default `https://gateway.polymarket.us`) in
addition to the api `base_url`, and add:
- `find_weather_markets(cities, limit=50)` → rows in the shape above PLUS
  pre-parsed `bucket_lo`, `bucket_hi`, `unit` (parsed via `parse_us_bucket`).
  Reuses `gamma`'s city-alias matching and `_parse_event_title` logic
  (factor the shared title/date parsing into a helper importable by both, to
  avoid duplicating the regex).
- `get_order_book(slug)` → normalized `{bids, asks, best_bid, best_ask,
  bid_depth, ask_depth}` via a **pure** `_normalize_book(raw)` (bids desc,
  offers→asks asc; depth = qty at best level, matching CLOB semantics).
- `get_event_resolutions(slugs)` → `{slug: 1|0|None}` from `/settlement`
  (404 / no settlement → None).

Keep splitting HTTP from parsing: `_normalize_book`, `_event_to_rows` are pure
functions so they can be unit-tested with captured fixtures offline.

### 3. `config.py` — data source flag

Add `data_source: Literal["us", "international"] = "us"` to `Settings`.

### 4. Data-provider selection

`InternationalData` adapter (new, thin) wraps `gamma`/`clob` to expose the same
three methods. A `build_data_provider(settings)` returns the US client
(`PolymarketUS.from_env()`) when `data_source == "us"`, else `InternationalData`.
If `"us"` and no credentials, raise a clear `RuntimeError` (US data requires
signing) rather than silently paper-trading the wrong venue.

### 5. `engine.py` wiring

- Build `self.data = build_data_provider(settings)` in `__init__`.
- Replace `gamma.find_weather_markets`, `clob.get_order_book`,
  `gamma.get_event_resolutions` with `self.data.*`.
- In `discover()`, prefer pre-parsed bounds when the row carries
  `bucket_lo`/`bucket_hi`/`unit`; else fall back to `parse_bucket(question)`.
  This keeps the international path working unchanged.

## Non-goals

- No WebSocket streaming yet (REST polling per cycle, matching current arch).
- No order placement (paper-only stance unchanged).

## Testing

- `parse_us_bucket`: offline unit tests for all three label forms.
- `_normalize_book`: offline test against the captured SF fixture.
- `_event_to_rows`: offline test mapping a captured climate event → bucket rows
  with correct city/date/bounds/slug.
- `build_data_provider`: returns international without creds; raises for "us"
  without creds (monkeypatched).
- Manual live smoke (not CI): `find_weather_markets` returns today's cities and
  one `get_order_book(slug)` returns a populated book.

## Verification

- New + existing tests green.
- Live: a paper cycle against `data_source: us` logs books for today's
  temperature buckets.
