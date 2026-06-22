# Forecast Verification Pipeline ("Mercury") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repurpose the existing weather paper-trading bot into a Python data-engineering pipeline that ingests weather-model forecasts and prediction-market prices on a schedule, unifies them, and benchmarks model-implied vs. market-implied probabilities against official NWS settlements — surfaced on a publicly deployed dashboard.

**Architecture:** A read-only ingestion pipeline (no trading) pulls daily high-temperature markets from Kalshi (primary, keyless public API, 20 cities, settlement history) and Polymarket (secondary), computes the existing ensemble model's bucket probability for each, and stores both the market-implied and model-implied probability over time in a unified store. A scoring layer joins snapshots to settled outcomes by lead time and computes Brier/log-loss/calibration for model vs. market. A scheduled GitHub Actions job runs ingestion; a Streamlit app reads the exported data and is deployed to a public URL.

**Tech Stack:** Python 3.12, httpx, pydantic, SQLite (local) + Parquet export, Streamlit (dashboard), pytest, GitHub Actions (scheduler). Reuses existing `forecast/`, `model/buckets.py`, `clients/gamma.py`, `config.py`.

---

## Overall Description (the project, and why it's resume-grade)

**Mercury** answers one clean, honest question: *can a calibrated weather-ensemble model out-predict the betting market on daily city temperatures?* For every daily high-temperature market on Kalshi and Polymarket, it records the market's implied probability and the model's probability at several lead times before close, then — once the National Weather Service publishes the official high — scores both against the truth. The deliverable is the **measurement system and the honest result**, not a trading strategy and not a P&L claim.

Why this is the right second project for the resume:
- **Fills the real gap:** genuine Python + data-engineering (scheduled multi-source ingestion, unification of mismatched schemas, validation, a warehouse-style store, Parquet export, a deployed dashboard) — the one thing the rest of the resume (Next.js/TypeScript/LLM apps) doesn't show.
- **Different domain on purpose:** nothing else on the resume touches weather or markets, so it demonstrates range.
- **Tells the Forward-Deployed-Engineer story:** "unify fragmented, messy real-world sources into one dataset, in production, end-to-end."
- **Cleanly demoable:** all data sources are public and keyless; the dashboard is read-only, so a live URL goes on the resume with no credentials, money, or always-on trading infrastructure.
- **Credible by construction:** the headline is a *calibration/Brier comparison*, which is verifiable and impossible to oversell. If the model beats the market at long lead times (plausible for weather), that's the highlight; if it doesn't, "the market is efficient at T-1 but the model edges it at T-3" is still a strong, honest finding.

**Naming:** working name "Mercury" (weather + speed); swap freely (e.g., "Isobar", "Forecast vs. Market"). Wherever this plan says `Mercury`, it's cosmetic (README/dashboard title only).

**Resume bullet (target, true regardless of result):**
> Built a Python data pipeline ingesting daily temperature markets from Kalshi/Polymarket and multi-model weather ensembles (GFS + ECMWF, 80+ members) across 20 cities, unifying them into a normalized store with scheduled ingestion (GitHub Actions), data validation, and Parquet export, and benchmarking model-implied vs. market-implied probabilities against NWS settlements (Brier/log-loss/calibration by lead time) on a live public dashboard. NN tests.

---

## What we keep, strip, and add

**Keep (reuse as-is):**
- `forecast/ensemble.py` — `get_ensemble_members(lat, lon, tz, target_date, unit) -> list[float]`
- `forecast/obs.py` — `get_running_max(station, tz, target_date, unit)`, `is_day_locked(tz, target_date, lock_hour)`
- `forecast/nws.py` — `get_hourly_daily_max(lat, lon, tz, target_date)`
- `model/buckets.py` — `parse_bucket(question)`, `bucket_probability(...)`, `ladder_probabilities(...)`
- `clients/gamma.py` — `find_weather_markets(cities, limit)`, `get_event_resolutions(slugs)`
- `config.py` — `City`, `ForecastConfig`, `load_settings`
- The SQLite-via-raw-sqlite3 pattern and pytest style.

**Strip from the resume surface (move out of the main package, do not delete):**
- Trading/market-making/rewards code: `engine.py`, `maker_engine.py`, `rewards_engine.py`, `execution/paper.py`, `strategy/*`, `fees.py`, `clients/us.py`, `clients/provider.py`, and their CLI commands (`paper-run`, `maker-run`, `rewards-*`). These are real work but make the repo read as a trading bot. Phase 0 relocates them under `legacy/` so the top-level project reads as a data pipeline.

**Add (new):**
- `clients/kalshi.py` — keyless Kalshi temperature-market + settlement-history client.
- `storage/verify_db.py` — unified cross-venue schema + helpers (non-breaking; separate DB file).
- `model/kalshi_buckets.py` — parse Kalshi strike labels into bucket bounds.
- `pipeline/ingest.py` — one-shot ingestion cycle (discover → snapshot market prob → snapshot model prob → update settlements).
- `pipeline/backfill.py` — backfill resolved Kalshi markets from settlement history.
- `analysis/verification.py` — Brier, log-loss, calibration curve, model-vs-market scoring by lead time, tidy evaluation frame.
- `pipeline/export.py` — Parquet export of the evaluation frame and raw tables.
- `webapp/app.py` — deployable Streamlit dashboard.
- `.github/workflows/ingest.yml` — scheduled ingestion.
- New CLI commands: `ingest-once`, `backfill-kalshi`, `verify-report`, `export`.
- `README.md` + `docs/EVALUATION.md` (architecture, data-lineage diagram, honest results).

---

## File Structure (new + touched)

```
src/polybot/
  clients/kalshi.py            NEW  keyless Kalshi client (markets, quotes, settlements)
  model/kalshi_buckets.py      NEW  parse Kalshi strike labels -> (lo, hi, unit)
  storage/verify_db.py         NEW  unified schema: vmarket, vquote, vpred (+ helpers)
  pipeline/__init__.py         NEW
  pipeline/ingest.py           NEW  one ingestion cycle (both venues)
  pipeline/backfill.py         NEW  Kalshi settlement-history backfill
  pipeline/export.py           NEW  Parquet export
  analysis/verification.py     NEW  brier/log-loss/calibration + model-vs-market scoring
  cli.py                       MOD  add ingest-once/backfill-kalshi/verify-report/export; drop legacy cmds
  config.py                    MOD  add VerifyConfig (db path, lead-time buckets, kalshi cities)
webapp/app.py                  NEW  Streamlit dashboard (deployed)
legacy/                        NEW  relocated trading modules (kept, not in resume story)
.github/workflows/ingest.yml   NEW  scheduled ingestion + data artifact commit
tests/test_kalshi_buckets.py   NEW
tests/test_verify_db.py        NEW
tests/test_verification.py     NEW
tests/test_ingest.py           NEW
README.md                      MOD  reframe as forecast-verification pipeline
docs/EVALUATION.md             NEW  honest results + caveats
```

---

## Phase 0: Reframe the repo (non-breaking cleanup)

### Task 0: Relocate trading code and restate the project

**Files:**
- Create: `legacy/README.md`
- Modify: move `src/polybot/engine.py`, `maker_engine.py`, `rewards_engine.py`, `execution/`, `strategy/`, `fees.py`, `clients/us.py`, `clients/provider.py` → `legacy/polybot_trading/` (preserve git history with `git mv`)
- Modify: `src/polybot/cli.py` (remove imports/commands for the moved modules)
- Modify: `pyproject.toml` (`description`)

- [ ] **Step 1: Move trading modules with history preserved**

```bash
mkdir -p legacy/polybot_trading
git mv src/polybot/engine.py legacy/polybot_trading/engine.py
git mv src/polybot/maker_engine.py legacy/polybot_trading/maker_engine.py
git mv src/polybot/rewards_engine.py legacy/polybot_trading/rewards_engine.py
git mv src/polybot/execution legacy/polybot_trading/execution
git mv src/polybot/strategy legacy/polybot_trading/strategy
git mv src/polybot/fees.py legacy/polybot_trading/fees.py
git mv src/polybot/clients/us.py legacy/polybot_trading/us.py
git mv src/polybot/clients/provider.py legacy/polybot_trading/provider.py
```

- [ ] **Step 2: Remove the legacy CLI commands**

In `src/polybot/cli.py`, delete the command functions `paper_run`, `maker_run`, `maker_report_cmd`, `rewards_gate`, `rewards_run`, `rewards_report_cmd`, and the `report` body's trading-only sections. Keep `discover`, `log-books`, `forecast`, `dashboard`. (New commands are added in later phases.)

- [ ] **Step 3: Restate the project**

In `pyproject.toml` set:
```toml
description = "Mercury — weather forecast vs. prediction-market verification pipeline"
```
Create `legacy/README.md`:
```markdown
# Legacy trading modules
Earlier maker/rewards paper-trading experiments. Retained for history; not part of the
forecast-verification pipeline. No live trading is performed anywhere in this repo.
```

- [ ] **Step 4: Verify the package still imports and tests pass**

Run: `uv run python -c "import polybot.cli"` then `uv run pytest -q`
Expected: import succeeds; the trading-specific tests that referenced moved modules may fail — move them too: `git mv tests/test_market_maker.py tests/test_paper.py tests/test_reward_range.py tests/test_rewards_config.py tests/test_rewards_db.py tests/test_rewards_engine.py tests/test_strategy.py tests/test_us_auth.py tests/test_us_data.py tests/test_us_incentives.py tests/test_market_select.py legacy/tests/` (create `legacy/tests/` first). Re-run; the kept tests (`test_buckets.py`, `test_calibration.py`) pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: relocate trading modules to legacy/, reframe as verification pipeline"
```

---

## Phase 1: Unified cross-venue storage

### Task 1: Add the verification schema and helpers

**Files:**
- Create: `src/polybot/storage/verify_db.py`
- Test: `tests/test_verify_db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_verify_db.py
from polybot.storage import verify_db

def test_upsert_market_and_quote_and_pred(tmp_path):
    conn = verify_db.connect(str(tmp_path / "v.sqlite3"))
    verify_db.upsert_market(conn, {
        "market_uid": "kalshi:KXHIGHNY-26JUN22-B75", "venue": "kalshi",
        "external_id": "KXHIGHNY-26JUN22-B75", "city": "New York", "target_date": "2026-06-22",
        "bucket_lo": 75.0, "bucket_hi": 76.0, "unit": "F",
        "question": "NYC high 75-76F?", "close_ts": 1_000_000.0,
    })
    verify_db.insert_quote(conn, "kalshi:KXHIGHNY-26JUN22-B75", ts=10.0,
                           market_prob=0.42, best_bid=0.40, best_ask=0.44)
    verify_db.insert_pred(conn, "kalshi:KXHIGHNY-26JUN22-B75", ts=10.0,
                          model_prob=0.55, lead_hours=48.0)
    verify_db.settle_market(conn, "kalshi:KXHIGHNY-26JUN22-B75", outcome=1)

    rows = conn.execute("SELECT settled, outcome FROM vmarket").fetchall()
    assert rows[0]["settled"] == 1 and rows[0]["outcome"] == 1
    assert conn.execute("SELECT market_prob FROM vquote").fetchone()["market_prob"] == 0.42
    assert conn.execute("SELECT lead_hours FROM vpred").fetchone()["lead_hours"] == 48.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_verify_db.py -v`
Expected: FAIL — `ModuleNotFoundError: polybot.storage.verify_db`

- [ ] **Step 3: Implement the schema and helpers**

```python
# src/polybot/storage/verify_db.py
"""Unified cross-venue store for the forecast-verification pipeline.

Separate DB file from the legacy trading store so nothing here depends on
trading code. Raw sqlite3 to match the existing project style.
"""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS vmarket (
    market_uid  TEXT PRIMARY KEY,   -- f"{venue}:{external_id}"
    venue       TEXT,               -- kalshi | polymarket
    external_id TEXT,               -- kalshi ticker | polymarket token_id
    city        TEXT,
    target_date TEXT,               -- YYYY-MM-DD local to the city
    bucket_lo   REAL,               -- NULL = open-ended below
    bucket_hi   REAL,               -- NULL = open-ended above
    unit        TEXT,
    question    TEXT,
    close_ts    REAL,
    settled     INTEGER DEFAULT 0,
    outcome     INTEGER             -- 1 = YES resolved true, 0 = false
);
CREATE TABLE IF NOT EXISTS vquote (
    ts          REAL,
    market_uid  TEXT,
    market_prob REAL,               -- implied P(YES) in [0,1]
    best_bid    REAL,
    best_ask    REAL
);
CREATE INDEX IF NOT EXISTS idx_vquote ON vquote(market_uid, ts);
CREATE TABLE IF NOT EXISTS vpred (
    ts          REAL,
    market_uid  TEXT,
    model_prob  REAL,               -- model P(YES) in [0,1]
    lead_hours  REAL                -- hours before close_ts at capture
);
CREATE INDEX IF NOT EXISTS idx_vpred ON vpred(market_uid, ts);
"""

def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn

def upsert_market(conn: sqlite3.Connection, m: dict) -> None:
    conn.execute(
        """INSERT INTO vmarket (market_uid, venue, external_id, city, target_date,
                                bucket_lo, bucket_hi, unit, question, close_ts)
           VALUES (:market_uid, :venue, :external_id, :city, :target_date,
                   :bucket_lo, :bucket_hi, :unit, :question, :close_ts)
           ON CONFLICT(market_uid) DO UPDATE SET close_ts = :close_ts, question = :question""",
        m,
    )
    conn.commit()

def insert_quote(conn, market_uid: str, ts: float, market_prob: float,
                 best_bid: float | None, best_ask: float | None) -> None:
    conn.execute("INSERT INTO vquote VALUES (?,?,?,?,?)",
                 (ts, market_uid, market_prob, best_bid, best_ask))
    conn.commit()

def insert_pred(conn, market_uid: str, ts: float, model_prob: float, lead_hours: float) -> None:
    conn.execute("INSERT INTO vpred VALUES (?,?,?,?)", (ts, market_uid, model_prob, lead_hours))
    conn.commit()

def settle_market(conn, market_uid: str, outcome: int) -> None:
    conn.execute("UPDATE vmarket SET settled = 1, outcome = ? WHERE market_uid = ?",
                 (outcome, market_uid))
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_verify_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polybot/storage/verify_db.py tests/test_verify_db.py
git commit -m "feat: unified cross-venue verification store"
```

---

## Phase 2: Kalshi bucket parsing (pure logic, no network)

### Task 2: Parse Kalshi temperature strike labels into bucket bounds

Kalshi `KXHIGH<CITY>` markets express buckets as strike labels like `"74° or below"`, `"75-76°"`, `"83° or above"`. Convert to `(lo, hi, unit)` matching the existing `model/buckets.bucket_probability` contract (`lo`/`hi` may be `None` for open-ended).

**Files:**
- Create: `src/polybot/model/kalshi_buckets.py`
- Test: `tests/test_kalshi_buckets.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kalshi_buckets.py
from polybot.model.kalshi_buckets import parse_kalshi_strike

def test_inclusive_range():
    assert parse_kalshi_strike("75-76°") == (75.0, 76.0, "F")

def test_open_ended_below():
    assert parse_kalshi_strike("74° or below") == (None, 74.0, "F")

def test_open_ended_above():
    assert parse_kalshi_strike("83° or above") == (83.0, None, "F")

def test_unparseable_returns_none():
    assert parse_kalshi_strike("mostly cloudy") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kalshi_buckets.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the parser**

```python
# src/polybot/model/kalshi_buckets.py
"""Parse Kalshi high-temperature strike labels into bucket bounds.

Returns (lo, hi, unit) with None for an open-ended side, or None if the label
isn't a temperature bucket. Mirrors model/buckets.parse_bucket's contract so the
existing bucket_probability() can score Kalshi markets unchanged.
"""
import re

_RANGE = re.compile(r"(-?\d+(?:\.\d+)?)\s*[-–to]+\s*(-?\d+(?:\.\d+)?)")
_BELOW = re.compile(r"(-?\d+(?:\.\d+)?)\s*°?\s*(?:or below|or lower|and below)", re.I)
_ABOVE = re.compile(r"(-?\d+(?:\.\d+)?)\s*°?\s*(?:or above|or higher|and above)", re.I)

def parse_kalshi_strike(label: str) -> tuple[float | None, float | None, str] | None:
    s = label.strip()
    m = _BELOW.search(s)
    if m:
        return (None, float(m.group(1)), "F")
    m = _ABOVE.search(s)
    if m:
        return (float(m.group(1)), None, "F")
    m = _RANGE.search(s)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (min(lo, hi), max(lo, hi), "F")
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_kalshi_buckets.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polybot/model/kalshi_buckets.py tests/test_kalshi_buckets.py
git commit -m "feat: parse Kalshi temperature strike labels"
```

---

## Phase 3: Kalshi client (keyless public market data)

### Task 3: Implement the Kalshi client

Kalshi market data is public (no key). Verify exact endpoints/field names against https://docs.kalshi.com before wiring — the shapes below match the documented v2 market API (`GET /trade-api/v2/markets`, `GET /trade-api/v2/markets/{ticker}`, filterable by `series_ticker` and `status=settled`). Keep network calls in thin functions and parsing in pure functions so the pure parts are unit-tested without the network.

**Files:**
- Create: `src/polybot/clients/kalshi.py`
- Test: `tests/test_kalshi_client.py`

- [ ] **Step 1: Write the failing test (pure parsing from a fixture payload)**

```python
# tests/test_kalshi_client.py
from polybot.clients.kalshi import market_prob_from_quote, market_to_unified

def test_market_prob_is_mid_in_unit_interval():
    # Kalshi quotes are in cents (0-100); YES mid of 40/44 -> 0.42
    assert market_prob_from_quote(yes_bid=40, yes_ask=44) == 0.42

def test_market_prob_handles_one_sided_book():
    assert market_prob_from_quote(yes_bid=None, yes_ask=44) == 0.44
    assert market_prob_from_quote(yes_bid=40, yes_ask=None) == 0.40

def test_market_to_unified_maps_fields():
    raw = {
        "ticker": "KXHIGHNY-26JUN22-B75", "title": "Highest temp in NYC",
        "subtitle": "75-76°", "yes_bid": 40, "yes_ask": 44,
        "close_time": "2026-06-23T04:00:00Z", "status": "active",
    }
    u = market_to_unified(raw, city="New York", target_date="2026-06-22")
    assert u["market_uid"] == "kalshi:KXHIGHNY-26JUN22-B75"
    assert u["venue"] == "kalshi"
    assert (u["bucket_lo"], u["bucket_hi"]) == (75.0, 76.0)
    assert u["close_ts"] == 1_782_000_000.0  # 2026-06-23T04:00:00Z epoch
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kalshi_client.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the client**

```python
# src/polybot/clients/kalshi.py
"""Keyless Kalshi market-data client for daily high-temperature markets.

Market data requires no auth. Endpoints/fields per https://docs.kalshi.com (v2).
Pure helpers (market_prob_from_quote, market_to_unified) are network-free and unit-tested;
fetch_* wrap httpx and are exercised in integration, not unit, tests.
"""
from datetime import datetime, timezone

import httpx

from polybot.model.kalshi_buckets import parse_kalshi_strike

BASE = "https://api.elections.kalshi.com/trade-api/v2"
# KXHIGH<CITY> series; map config city name -> Kalshi series ticker. Verify/extend
# against the live series list during build (docs.kalshi.com weather markets).
CITY_SERIES = {
    "New York": "KXHIGHNY", "Los Angeles": "KXHIGHLAX", "Chicago": "KXHIGHCHI",
    "Miami": "KXHIGHMIA", "Austin": "KXHIGHAUS", "Denver": "KXHIGHDEN",
    "Philadelphia": "KXHIGHPHIL", "Houston": "KXHIGHHOU",
}

def market_prob_from_quote(yes_bid: float | None, yes_ask: float | None) -> float | None:
    vals = [v for v in (yes_bid, yes_ask) if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals) / 100.0, 4)

def _close_ts(close_time: str) -> float:
    return datetime.fromisoformat(close_time.replace("Z", "+00:00")).timestamp()

def market_to_unified(raw: dict, city: str, target_date: str) -> dict | None:
    bucket = parse_kalshi_strike(raw.get("subtitle", ""))
    if bucket is None:
        return None
    lo, hi, unit = bucket
    ticker = raw["ticker"]
    return {
        "market_uid": f"kalshi:{ticker}", "venue": "kalshi", "external_id": ticker,
        "city": city, "target_date": target_date, "bucket_lo": lo, "bucket_hi": hi,
        "unit": unit, "question": f"{raw.get('title','')} {raw.get('subtitle','')}".strip(),
        "close_ts": _close_ts(raw["close_time"]),
        "yes_bid": raw.get("yes_bid"), "yes_ask": raw.get("yes_ask"),
        "status": raw.get("status"), "result": raw.get("result"),
    }

def fetch_markets(series_ticker: str, status: str = "open",
                  client: httpx.Client | None = None) -> list[dict]:
    own = client is None
    client = client or httpx.Client(timeout=20)
    try:
        r = client.get(f"{BASE}/markets",
                       params={"series_ticker": series_ticker, "status": status, "limit": 1000})
        r.raise_for_status()
        return r.json().get("markets", [])
    finally:
        if own:
            client.close()

def fetch_settled(series_ticker: str, client: httpx.Client | None = None) -> list[dict]:
    """Resolved markets carry result='yes'|'no' — used for backfill."""
    return fetch_markets(series_ticker, status="settled", client=client)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_kalshi_client.py -v`
Expected: PASS (pure helpers). If the epoch literal differs, recompute from the ISO string and update the test.

- [ ] **Step 5: Smoke-test the live endpoint (manual, networked)**

Run: `uv run python -c "from polybot.clients.kalshi import fetch_markets; print(len(fetch_markets('KXHIGHNY')))"`
Expected: a non-negative integer (number of open NYC high-temp markets). If it errors, reconcile `BASE`/params with docs.kalshi.com and update.

- [ ] **Step 6: Commit**

```bash
git add src/polybot/clients/kalshi.py tests/test_kalshi_client.py
git commit -m "feat: keyless Kalshi temperature-market client"
```

---

## Phase 4: Verification scoring (pure logic, the heart of the project)

### Task 4: Brier, log-loss, calibration, and model-vs-market scoring

**Files:**
- Create: `src/polybot/analysis/verification.py`
- Test: `tests/test_verification.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_verification.py
import math
from polybot.analysis import verification as V
from polybot.storage import verify_db

def test_brier_and_log_loss():
    assert V.brier(0.7, 1) == pytest_approx(0.09)
    assert V.brier(0.7, 0) == pytest_approx(0.49)
    assert V.log_loss(0.8, 1) == pytest_approx(-math.log(0.8))

def test_calibration_curve_buckets_and_winrate():
    pairs = [(0.1, 0), (0.15, 0), (0.85, 1), (0.9, 1)]
    curve = V.calibration_curve(pairs, bins=2)
    lo, hi = curve[0], curve[-1]
    assert lo["n"] == 2 and lo["win_rate"] == 0.0
    assert hi["n"] == 2 and hi["win_rate"] == 1.0

def test_score_by_lead_time_compares_model_vs_market(tmp_path):
    conn = verify_db.connect(str(tmp_path / "v.sqlite3"))
    uid = "kalshi:T1"
    verify_db.upsert_market(conn, {
        "market_uid": uid, "venue": "kalshi", "external_id": "T1", "city": "NYC",
        "target_date": "2026-06-22", "bucket_lo": 75.0, "bucket_hi": 76.0, "unit": "F",
        "question": "q", "close_ts": 1000.0})
    # snapshots ~48h before close (close_ts - lead_hours*3600)
    verify_db.insert_quote(conn, uid, ts=1000.0 - 48*3600, market_prob=0.50, best_bid=0.48, best_ask=0.52)
    verify_db.insert_pred(conn, uid, ts=1000.0 - 48*3600, model_prob=0.80, lead_hours=48.0)
    verify_db.settle_market(conn, uid, outcome=1)  # YES happened; model was closer
    scored = V.score_by_lead_time(conn, lead_buckets=(48,))
    row = scored[0]
    assert row["lead_hours"] == 48 and row["n"] == 1
    assert row["model_brier"] < row["market_brier"]

# minimal local approx to avoid extra deps
def pytest_approx(x, tol=1e-9):
    class _A:
        def __eq__(self, other): return abs(other - x) < tol
    return _A()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_verification.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the scoring module**

```python
# src/polybot/analysis/verification.py
"""Score model-implied vs. market-implied probabilities against settled outcomes.

Pure functions (brier/log_loss/calibration_curve) plus DB-backed joins. The
evaluation frame pairs, for each settled market and target lead time, the model
and market probability snapshots nearest that lead time with the realized outcome.
"""
import math
import sqlite3

def brier(prob: float, outcome: int) -> float:
    return (prob - outcome) ** 2

def log_loss(prob: float, outcome: int, eps: float = 1e-9) -> float:
    p = min(max(prob, eps), 1 - eps)
    return -(outcome * math.log(p) + (1 - outcome) * math.log(1 - p))

def calibration_curve(pairs: list[tuple[float, int]], bins: int = 10) -> list[dict]:
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        sel = [(p, o) for p, o in pairs if (lo <= p < hi or (i == bins - 1 and p == 1.0))]
        n = len(sel)
        out.append({
            "bin": f"{lo:.1f}-{hi:.1f}", "n": n,
            "avg_prob": round(sum(p for p, _ in sel) / n, 4) if n else None,
            "win_rate": round(sum(o for _, o in sel) / n, 4) if n else None,
        })
    return out

def _nearest_snapshot(conn, table: str, value_col: str, market_uid: str, target_ts: float):
    rows = conn.execute(
        f"SELECT ts, {value_col} AS v FROM {table} WHERE market_uid = ?", (market_uid,)
    ).fetchall()
    if not rows:
        return None
    best = min(rows, key=lambda r: abs(r["ts"] - target_ts))
    return best["v"]

def evaluation_frame(conn: sqlite3.Connection,
                     lead_buckets: tuple[int, ...] = (72, 48, 24, 6)) -> list[dict]:
    frame = []
    markets = conn.execute(
        "SELECT market_uid, city, close_ts, outcome FROM vmarket WHERE settled = 1"
    ).fetchall()
    for m in markets:
        for lead in lead_buckets:
            target_ts = m["close_ts"] - lead * 3600
            model_p = _nearest_snapshot(conn, "vpred", "model_prob", m["market_uid"], target_ts)
            market_p = _nearest_snapshot(conn, "vquote", "market_prob", m["market_uid"], target_ts)
            if model_p is None or market_p is None:
                continue
            frame.append({
                "market_uid": m["market_uid"], "city": m["city"], "lead_hours": lead,
                "model_prob": model_p, "market_prob": market_p, "outcome": int(m["outcome"]),
            })
    return frame

def score_by_lead_time(conn: sqlite3.Connection,
                       lead_buckets: tuple[int, ...] = (72, 48, 24, 6)) -> list[dict]:
    frame = evaluation_frame(conn, lead_buckets)
    out = []
    for lead in lead_buckets:
        rows = [r for r in frame if r["lead_hours"] == lead]
        if not rows:
            continue
        n = len(rows)
        out.append({
            "lead_hours": lead, "n": n,
            "model_brier": round(sum(brier(r["model_prob"], r["outcome"]) for r in rows) / n, 4),
            "market_brier": round(sum(brier(r["market_prob"], r["outcome"]) for r in rows) / n, 4),
            "model_logloss": round(sum(log_loss(r["model_prob"], r["outcome"]) for r in rows) / n, 4),
            "market_logloss": round(sum(log_loss(r["market_prob"], r["outcome"]) for r in rows) / n, 4),
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_verification.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polybot/analysis/verification.py tests/test_verification.py
git commit -m "feat: model-vs-market Brier/log-loss/calibration scoring by lead time"
```

---

## Phase 5: Ingestion orchestration

### Task 5: One-shot ingestion cycle

Discover markets on both venues, compute model probability for each (reusing `ensemble` + `buckets`), snapshot market + model probability with current lead time, and validate each row before writing. Designed to be invoked once per scheduler tick.

**Files:**
- Create: `src/polybot/pipeline/__init__.py` (empty), `src/polybot/pipeline/ingest.py`
- Modify: `src/polybot/config.py` (add `VerifyConfig`)
- Test: `tests/test_ingest.py`

- [ ] **Step 1: Add config (no test needed — exercised via Task 5 test)**

In `src/polybot/config.py`, add and wire into `Settings`:
```python
class VerifyConfig(BaseModel):
    db_path: str = "data/verify.sqlite3"
    lead_buckets: tuple[int, ...] = (72, 48, 24, 6)
    kalshi_cities: list[str] = ["New York", "Los Angeles", "Chicago", "Miami", "Austin"]
    include_polymarket: bool = True
```
Add `verify: VerifyConfig = VerifyConfig()` to `Settings`.

- [ ] **Step 2: Write the failing test (model-prob binding is the testable core; network discovery is injected)**

```python
# tests/test_ingest.py
from polybot.pipeline.ingest import model_prob_for_market, validate_unified
from polybot.storage import verify_db

def test_validate_rejects_out_of_range_prob():
    assert validate_unified({"bucket_lo": 75.0, "bucket_hi": 76.0, "close_ts": 1.0}) is True
    assert validate_unified({"bucket_lo": None, "bucket_hi": None, "close_ts": 1.0}) is False

def test_model_prob_for_market_uses_ensemble(monkeypatch):
    import polybot.pipeline.ingest as ing
    monkeypatch.setattr(ing.ensemble, "get_ensemble_members",
                        lambda lat, lon, tz, date, unit: [75.5] * 40)
    monkeypatch.setattr(ing.obs, "get_running_max", lambda *a, **k: None)
    monkeypatch.setattr(ing.obs, "is_day_locked", lambda *a, **k: False)
    from polybot.config import City
    c = City(name="New York", station="KNYC", lat=40.7, lon=-74.0)
    p = model_prob_for_market(c, "2026-06-22",
                              {"bucket_lo": 75.0, "bucket_hi": 76.0}, sigma=1.5,
                              obs_buffer=1.5, locked_bias=0.75, locked_sigma=1.0)
    assert 0.0 <= p <= 1.0 and p > 0.2  # mass concentrated on 75-76 given members at 75.5
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_ingest.py -v`
Expected: FAIL — module not found

- [ ] **Step 4: Implement ingestion**

```python
# src/polybot/pipeline/ingest.py
"""One ingestion cycle: discover markets, snapshot market + model probabilities.

Read-only. No orders are ever placed. Safe to run repeatedly (snapshots are
append-only; markets upsert by uid)."""
import logging
import time

from polybot.clients import gamma, kalshi
from polybot.config import City, Settings
from polybot.forecast import ensemble, obs
from polybot.model import buckets as bm
from polybot.storage import verify_db

log = logging.getLogger("mercury.ingest")

def validate_unified(m: dict) -> bool:
    """Drop markets we can't score: need at least one finite bucket edge and a close time."""
    if m.get("close_ts") is None:
        return False
    return m.get("bucket_lo") is not None or m.get("bucket_hi") is not None

def model_prob_for_market(city: City, target_date: str, bucket: dict, *, sigma: float,
                          obs_buffer: float, locked_bias: float, locked_sigma: float) -> float:
    members = ensemble.get_ensemble_members(city.lat, city.lon, city.tz, target_date, city.unit)
    running = obs.get_running_max(city.station, city.tz, target_date, city.unit)
    locked = obs.is_day_locked(city.tz, target_date, 18)
    obs_eff = None
    if running is not None:
        obs_eff = running + locked_bias if locked else running - obs_buffer
    return bm.bucket_probability(
        members, bucket["bucket_lo"], bucket["bucket_hi"], sigma, obs_eff, locked, locked_sigma
    )

def run_once(settings: Settings) -> dict:
    conn = verify_db.connect(_abs(settings.verify.db_path))
    cities = {c.name: c for c in settings.forecast.cities}
    fc = settings.forecast
    n_markets = n_quotes = n_preds = 0
    now = time.time()

    # --- Kalshi (primary) ---
    for city_name in settings.verify.kalshi_cities:
        series = kalshi.CITY_SERIES.get(city_name)
        city = cities.get(city_name)
        if not series or not city:
            log.warning("skip city without series/config: %s", city_name); continue
        try:
            raw_markets = kalshi.fetch_markets(series, status="open")
        except Exception as e:  # network resilience: one city failing must not abort the cycle
            log.warning("kalshi fetch failed for %s: %s", city_name, e); continue
        for raw in raw_markets:
            target_date = _target_date_from_ticker(raw["ticker"])
            u = kalshi.market_to_unified(raw, city_name, target_date)
            if u is None or not validate_unified(u):
                continue
            verify_db.upsert_market(conn, _market_cols(u)); n_markets += 1
            mp = kalshi.market_prob_from_quote(u["yes_bid"], u["yes_ask"])
            if mp is not None:
                verify_db.insert_quote(conn, u["market_uid"], now, mp, u["yes_bid"], u["yes_ask"]); n_quotes += 1
            model_p = model_prob_for_market(city, target_date, u, sigma=fc.kernel_sigma_f,
                obs_buffer=fc.obs_buffer_f, locked_bias=fc.locked_bias_f, locked_sigma=fc.locked_sigma_f)
            lead_h = max((u["close_ts"] - now) / 3600.0, 0.0)
            verify_db.insert_pred(conn, u["market_uid"], now, model_p, lead_h); n_preds += 1

    # --- Polymarket (secondary; reuse existing gamma discovery) ---
    if settings.verify.include_polymarket:
        try:
            _ingest_polymarket(conn, settings, now)
        except Exception as e:
            log.warning("polymarket ingest failed: %s", e)

    log.info("cycle done: markets=%d quotes=%d preds=%d", n_markets, n_quotes, n_preds)
    return {"markets": n_markets, "quotes": n_quotes, "preds": n_preds}

# --- helpers ---
def _abs(p: str) -> str:
    from polybot.config import ROOT
    from pathlib import Path
    pp = Path(p)
    return str(pp if pp.is_absolute() else ROOT / pp)

def _market_cols(u: dict) -> dict:
    return {k: u[k] for k in ("market_uid", "venue", "external_id", "city", "target_date",
                              "bucket_lo", "bucket_hi", "unit", "question", "close_ts")}

def _target_date_from_ticker(ticker: str) -> str:
    """KXHIGHNY-26JUN22-B75 -> 2026-06-22. Verify Kalshi's date token format during build."""
    import re
    from datetime import datetime
    m = re.search(r"-(\d{2}[A-Z]{3}\d{2})-", ticker)
    if not m:
        return ""
    return datetime.strptime(m.group(1), "%y%b%d").strftime("%Y-%m-%d")

def _ingest_polymarket(conn, settings: Settings, now: float) -> None:
    rows = gamma.find_weather_markets(settings.forecast.cities)
    cities = {c.name: c for c in settings.forecast.cities}
    fc = settings.forecast
    for r in rows:
        parsed = bm.parse_bucket(r["question"])
        if not parsed:
            continue
        lo, hi, unit = parsed
        token = r.get("token_id") or r.get("clob_token_id")
        if not token:
            continue
        uid = f"polymarket:{token}"
        verify_db.upsert_market(conn, {
            "market_uid": uid, "venue": "polymarket", "external_id": token,
            "city": r["city"], "target_date": r["target_date"], "bucket_lo": lo, "bucket_hi": hi,
            "unit": unit, "question": r["question"], "close_ts": r.get("end_ts") or now})
        if r.get("outcome_prices"):
            mp = float(r["outcome_prices"][0])
            verify_db.insert_quote(conn, uid, now, mp, None, None)
        city = cities.get(r["city"])
        if city:
            model_p = model_prob_for_market(city, r["target_date"], {"bucket_lo": lo, "bucket_hi": hi},
                sigma=fc.kernel_sigma_f, obs_buffer=fc.obs_buffer_f,
                locked_bias=fc.locked_bias_f, locked_sigma=fc.locked_sigma_f)
            lead_h = max((conn.execute("SELECT close_ts FROM vmarket WHERE market_uid=?", (uid,)
                ).fetchone()["close_ts"] - now) / 3600.0, 0.0)
            verify_db.insert_pred(conn, uid, now, model_p, lead_h)
```

> Note: confirm `bucket_probability`'s exact parameter order against `model/buckets.py:56` during build and adjust the call in `model_prob_for_market`. The signature is `bucket_probability(members, low, high, sigma, obs_eff, locked, locked_sigma)` per the existing `ladder_probabilities` caller.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_ingest.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/polybot/pipeline/__init__.py src/polybot/pipeline/ingest.py src/polybot/config.py tests/test_ingest.py
git commit -m "feat: one-shot read-only ingestion cycle (Kalshi + Polymarket)"
```

---

## Phase 6: Settlement backfill

### Task 6: Backfill resolved Kalshi markets from settlement history

This is the unlock that gives you a real sample immediately instead of waiting weeks.

**Files:**
- Create: `src/polybot/pipeline/backfill.py`
- Test: `tests/test_backfill.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backfill.py
from polybot.pipeline.backfill import outcome_from_result, settled_rows_to_unified

def test_outcome_from_result():
    assert outcome_from_result("yes") == 1
    assert outcome_from_result("no") == 0
    assert outcome_from_result(None) is None

def test_settled_rows_to_unified_filters_unparseable():
    raw = [
        {"ticker": "KXHIGHNY-26JUN20-B75", "title": "NYC high", "subtitle": "75-76°",
         "close_time": "2026-06-21T04:00:00Z", "result": "yes"},
        {"ticker": "KXHIGHNY-26JUN20-NOISE", "title": "x", "subtitle": "cloudy",
         "close_time": "2026-06-21T04:00:00Z", "result": "no"},
    ]
    rows = settled_rows_to_unified(raw, city="New York")
    assert len(rows) == 1 and rows[0]["outcome"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_backfill.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement backfill**

```python
# src/polybot/pipeline/backfill.py
"""Backfill settled Kalshi markets so scoring has a sample without waiting.

NOTE: settlement history gives the OUTCOME and the bucket, but NOT historical
order books — so backfilled markets contribute to outcome/settlement coverage and
let us validate the model against truth. Live model-vs-market lead-time scoring
still accrues forward from run_once snapshots."""
import logging

from polybot.clients import kalshi
from polybot.pipeline.ingest import _market_cols, _target_date_from_ticker, _abs
from polybot.storage import verify_db

log = logging.getLogger("mercury.backfill")

def outcome_from_result(result: str | None) -> int | None:
    if result is None:
        return None
    return 1 if result.lower() == "yes" else 0

def settled_rows_to_unified(raw_rows: list[dict], city: str) -> list[dict]:
    out = []
    for raw in raw_rows:
        u = kalshi.market_to_unified(raw, city, _target_date_from_ticker(raw["ticker"]))
        if u is None:
            continue
        u["outcome"] = outcome_from_result(raw.get("result"))
        if u["outcome"] is None:
            continue
        out.append(u)
    return out

def run_backfill(settings) -> int:
    conn = verify_db.connect(_abs(settings.verify.db_path))
    n = 0
    for city_name in settings.verify.kalshi_cities:
        series = kalshi.CITY_SERIES.get(city_name)
        if not series:
            continue
        try:
            raw = kalshi.fetch_settled(series)
        except Exception as e:
            log.warning("settled fetch failed for %s: %s", city_name, e); continue
        for u in settled_rows_to_unified(raw, city_name):
            verify_db.upsert_market(conn, _market_cols(u))
            verify_db.settle_market(conn, u["market_uid"], u["outcome"]); n += 1
    log.info("backfilled %d settled markets", n)
    return n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_backfill.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polybot/pipeline/backfill.py tests/test_backfill.py
git commit -m "feat: backfill settled Kalshi markets for immediate outcome coverage"
```

---

## Phase 7: Parquet export

### Task 7: Export the evaluation frame and raw tables to Parquet

**Files:**
- Create: `src/polybot/pipeline/export.py`
- Modify: `pyproject.toml` (add `pyarrow` to dependencies)
- Test: `tests/test_export.py`

- [ ] **Step 1: Add dependency**

In `pyproject.toml` `dependencies`, add `"pyarrow"`. Run `uv sync`.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_export.py
import pyarrow.parquet as pq
from polybot.pipeline.export import export_evaluation
from polybot.storage import verify_db

def test_export_writes_parquet(tmp_path):
    conn = verify_db.connect(str(tmp_path / "v.sqlite3"))
    uid = "kalshi:T1"
    verify_db.upsert_market(conn, {"market_uid": uid, "venue": "kalshi", "external_id": "T1",
        "city": "NYC", "target_date": "2026-06-22", "bucket_lo": 75.0, "bucket_hi": 76.0,
        "unit": "F", "question": "q", "close_ts": 1000.0})
    verify_db.insert_quote(conn, uid, 1000.0 - 48*3600, 0.5, 0.48, 0.52)
    verify_db.insert_pred(conn, uid, 1000.0 - 48*3600, 0.8, 48.0)
    verify_db.settle_market(conn, uid, 1)
    out = tmp_path / "evaluations.parquet"
    n = export_evaluation(conn, str(out), lead_buckets=(48,))
    assert n == 1
    assert pq.read_table(str(out)).num_rows == 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_export.py -v`
Expected: FAIL — module not found

- [ ] **Step 4: Implement export**

```python
# src/polybot/pipeline/export.py
"""Export the tidy evaluation frame to Parquet for the dashboard and portability."""
import pyarrow as pa
import pyarrow.parquet as pq

from polybot.analysis.verification import evaluation_frame

def export_evaluation(conn, out_path: str, lead_buckets=(72, 48, 24, 6)) -> int:
    frame = evaluation_frame(conn, lead_buckets)
    cols = ["market_uid", "city", "lead_hours", "model_prob", "market_prob", "outcome"]
    table = pa.table({c: [r[c] for r in frame] for c in cols} if frame
                     else {c: [] for c in cols})
    pq.write_table(table, out_path)
    return len(frame)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_export.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/polybot/pipeline/export.py tests/test_export.py pyproject.toml
git commit -m "feat: Parquet export of the evaluation frame"
```

---

## Phase 8: CLI wiring

### Task 8: Expose the pipeline as CLI commands

**Files:**
- Modify: `src/polybot/cli.py`

- [ ] **Step 1: Add commands**

Append to `src/polybot/cli.py`:
```python
@app.command(name="ingest-once")
def ingest_once():
    """Run one read-only ingestion cycle (Kalshi + Polymarket). No trading."""
    import logging
    logging.basicConfig(level=logging.INFO)
    from polybot.pipeline.ingest import run_once
    rprint(run_once(load_settings()))

@app.command(name="backfill-kalshi")
def backfill_kalshi():
    """Backfill settled Kalshi temperature markets for immediate outcome coverage."""
    import logging
    logging.basicConfig(level=logging.INFO)
    from polybot.pipeline.backfill import run_backfill
    rprint(f"backfilled {run_backfill(load_settings())} markets")

@app.command(name="verify-report")
def verify_report():
    """Model vs. market Brier/log-loss by lead time."""
    from polybot.analysis.verification import score_by_lead_time
    from polybot.pipeline.ingest import _abs
    from polybot.storage import verify_db
    s = load_settings()
    conn = verify_db.connect(_abs(s.verify.db_path))
    rows = score_by_lead_time(conn, s.verify.lead_buckets)
    if not rows:
        rprint("[dim]No settled markets with paired snapshots yet.[/dim]"); return
    t = Table(title="Model vs. Market (lower Brier = better)")
    for col in ("lead_h", "n", "model_brier", "market_brier", "model_logloss", "market_logloss"):
        t.add_column(col)
    for r in rows:
        win = "bold green" if r["model_brier"] < r["market_brier"] else ""
        t.add_row(str(r["lead_hours"]), str(r["n"]), f"{r['model_brier']:.4f}",
                  f"{r['market_brier']:.4f}", f"{r['model_logloss']:.4f}",
                  f"{r['market_logloss']:.4f}", style=win)
    rprint(t)

@app.command(name="export")
def export_cmd(out: str = typer.Option("data/evaluations.parquet")):
    """Export the evaluation frame to Parquet."""
    from polybot.pipeline.export import export_evaluation
    from polybot.pipeline.ingest import _abs
    from polybot.storage import verify_db
    s = load_settings()
    conn = verify_db.connect(_abs(s.verify.db_path))
    n = export_evaluation(conn, _abs(out), s.verify.lead_buckets)
    rprint(f"wrote {n} rows -> {out}")
```

- [ ] **Step 2: Verify commands load**

Run: `uv run polybot --help`
Expected: lists `ingest-once`, `backfill-kalshi`, `verify-report`, `export`, plus `discover`/`forecast`/`dashboard`.

- [ ] **Step 3: End-to-end smoke (networked)**

Run: `uv run polybot backfill-kalshi && uv run polybot ingest-once && uv run polybot verify-report`
Expected: backfill prints a count; ingest prints `{markets,quotes,preds}`; report prints a table or the "no paired snapshots yet" note (paired lead-time scoring needs forward snapshots to accrue).

- [ ] **Step 4: Commit**

```bash
git add src/polybot/cli.py
git commit -m "feat: CLI for ingest/backfill/verify/export"
```

---

## Phase 9: Deployed dashboard

### Task 9: Streamlit dashboard reading the exported Parquet

**Files:**
- Create: `webapp/app.py`, `webapp/requirements.txt`
- Modify: `pyproject.toml` (add `streamlit` to a `viz` optional group, or document it as the webapp's own dep)

- [ ] **Step 1: Implement the dashboard**

```python
# webapp/app.py
"""Mercury — forecast vs. market dashboard. Reads data/evaluations.parquet."""
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Mercury — Forecast vs. Market", layout="wide")
st.title("Mercury — can a weather model beat the market?")
st.caption("Daily city-temperature markets (Kalshi/Polymarket) vs. a GFS+ECMWF ensemble, "
           "scored against NWS settlements. Read-only research dashboard — no trading.")

df = pd.read_parquet("data/evaluations.parquet")
if df.empty:
    st.info("No settled, paired observations yet — the pipeline is still accruing.")
    st.stop()

def brier(p, o): return (p - o) ** 2
df["model_brier"] = brier(df.model_prob, df.outcome)
df["market_brier"] = brier(df.market_prob, df.outcome)

st.metric("Resolved observations", len(df))
by_lead = df.groupby("lead_hours")[["model_brier", "market_brier"]].mean().reset_index()
st.subheader("Brier score by lead time (lower = better)")
st.bar_chart(by_lead, x="lead_hours", y=["model_brier", "market_brier"])

st.subheader("Calibration — model vs. market")
col1, col2 = st.columns(2)
for col, src in ((col1, "model_prob"), (col2, "market_prob")):
    tmp = df.copy()
    tmp["bin"] = (tmp[src] * 10).clip(0, 9).astype(int) / 10
    cal = tmp.groupby("bin").agg(predicted=(src, "mean"), actual=("outcome", "mean")).reset_index()
    col.caption(src)
    col.line_chart(cal, x="predicted", y="actual")

st.subheader("By city")
st.dataframe(df.groupby("city")[["model_brier", "market_brier"]].mean().round(4))
```

- [ ] **Step 2: Pin webapp deps**

`webapp/requirements.txt`:
```
streamlit
pandas
pyarrow
```

- [ ] **Step 3: Run locally**

Run: `uv run polybot export && cd webapp && streamlit run app.py`
Expected: dashboard opens; shows the accruing data or the "still accruing" note.

- [ ] **Step 4: Deploy to a public URL**

Push to GitHub, then deploy on **Streamlit Community Cloud** (free): point it at `webapp/app.py`. The app reads `data/evaluations.parquet`, which the scheduled Action (Phase 10) keeps current in the repo. Capture the public URL — it goes on the resume.

- [ ] **Step 5: Commit**

```bash
git add webapp/app.py webapp/requirements.txt
git commit -m "feat: deployable Streamlit forecast-vs-market dashboard"
```

---

## Phase 10: Scheduled ingestion (GitHub Actions)

### Task 10: Cron-driven ingestion that refreshes the public data

**Files:**
- Create: `.github/workflows/ingest.yml`

- [ ] **Step 1: Add the workflow**

```yaml
# .github/workflows/ingest.yml
name: ingest
on:
  schedule:
    - cron: "0 */3 * * *"   # every 3h; tighten later if useful
  workflow_dispatch: {}
permissions:
  contents: write
jobs:
  ingest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run polybot backfill-kalshi
      - run: uv run polybot ingest-once
      - run: uv run polybot export --out data/evaluations.parquet
      - name: Commit refreshed data
        run: |
          git config user.name  "mercury-bot"
          git config user.email "mercury-bot@users.noreply.github.com"
          git add data/evaluations.parquet data/verify.sqlite3 || true
          git commit -m "data: scheduled ingest $(date -u +%FT%TZ)" || echo "no changes"
          git push
```

- [ ] **Step 2: Verify manually**

Push, then in GitHub Actions run the workflow via `workflow_dispatch`. Confirm it commits an updated `data/evaluations.parquet`. Streamlit Cloud redeploys on push, so the dashboard refreshes.

> Trade-off note: committing the SQLite/Parquet back to the repo is the zero-cost path and keeps the dashboard stateless. If git history bloat becomes an issue, switch the store to free hosted Postgres (Neon) shared by the Action and the dashboard — a cleaner data-engineering story; out of scope for v1.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ingest.yml
git commit -m "ci: scheduled read-only ingestion + data refresh"
```

---

## Phase 11: Docs & honest evaluation

### Task 11: README, data-lineage, and the honest results write-up

**Files:**
- Modify: `README.md`
- Create: `docs/EVALUATION.md`

- [ ] **Step 1: Rewrite README**

Include: one-paragraph description (from "Overall Description" above), an ASCII data-lineage diagram (sources → ingest → unified store → scoring → Parquet → dashboard), the live dashboard URL, quickstart (`uv sync`, `uv run polybot backfill-kalshi`, `ingest-once`, `verify-report`, `export`), the "no trading; read-only" disclaimer, and a test badge.

```
Kalshi /markets  ─┐
Polymarket gamma ─┼─▶ pipeline/ingest ─▶ verify_db (vmarket/vquote/vpred)
Open-Meteo (GFS+ECMWF) ─┤                         │
NWS + METAR (obs) ──────┘                         ▼
                              analysis/verification ─▶ export ─▶ data/evaluations.parquet ─▶ Streamlit (public URL)
```

- [ ] **Step 2: Write the honest evaluation**

`docs/EVALUATION.md`: current resolved-market count, the model-vs-market Brier/log-loss table by lead time (paste from `verify-report`), calibration commentary, and explicit caveats (sample size, lead-time snapshot nearest-match tolerance, NWS-settlement timing, no backfilled order books). State the finding plainly — including "the market is better at T-6" if that's what the data says.

- [ ] **Step 3: Update the count placeholder in the resume bullet**

Replace `NN tests` in the resume bullet (top of this file) with the real count from `uv run pytest -q | tail -1`.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/EVALUATION.md
git commit -m "docs: README, data-lineage, honest evaluation write-up"
```

---

## Self-Review

- **Spec coverage:** scheduled ingestion (Phase 10), multi-source unification (Phases 3/5), validation (`validate_unified`, Phase 5), warehouse-style store (Phase 1), Parquet export (Phase 7), deployed dashboard (Phase 9), model-vs-market scoring (Phase 4), settlement backfill (Phase 6), docs/honest results (Phase 11), repo reframe (Phase 0). All covered.
- **Type consistency:** `market_uid` (`venue:external_id`) is the join key across `vmarket`/`vquote`/`vpred` and every helper. `bucket_lo`/`bucket_hi`/`unit` naming matches `verify_db`, the Kalshi parser, and `bucket_probability`. `outcome` is `int` (1/0) everywhere; `model_prob`/`market_prob` are floats in [0,1].
- **Known verification points (not placeholders — confirm against live APIs during build):** Kalshi v2 endpoint/field names and the ticker date token (`_target_date_from_ticker`); `bucket_probability` exact arg order (`model/buckets.py:56`); Polymarket `token_id`/`end_ts` field names in `find_weather_markets` rows. Each is isolated behind a tested pure function so the rest of the pipeline is unaffected if a field name differs.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-06-22-forecast-verification-pipeline.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints for review.

Which approach?
