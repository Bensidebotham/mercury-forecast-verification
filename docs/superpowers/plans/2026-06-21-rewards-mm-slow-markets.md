# Rewards-MM on Slow Polymarket US Markets — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a paper simulator that estimates the net daily PnL (`rewards − adverse-selection − fees`) of resting two-sided maker quotes on slow Politics/Macro/Culture markets on Polymarket US, to prove the *sign* of net before any real capital.

**Architecture:** Reuse the existing quoting + reward-scoring machinery in `strategy/market_maker.py` (which already works with `model_prob=None` → pure book-mid fair value) and the simulated fills/settlement in `execution/paper.py`. Add four new pieces: (1) generic *category* market discovery + per-market reward params on the `PolymarketUS` client, gated by a Phase-0 probe; (2) a `model/slowness.py` adverse-selection-risk classifier; (3) an optimistic/pessimistic `estimate_reward_range`; (4) a `RewardsEngine` loop decoupled from weather forecasts/lock state, writing to a separate `data/rewards.sqlite3`.

**Tech Stack:** Python 3.13/3.14, `httpx`, `cryptography` (Ed25519), `pydantic`, `typer`, `rich`, `sqlite3`, `pytest`, `uv`.

**Spec:** `docs/superpowers/specs/2026-06-21-rewards-mm-simulator-design.md`

> **⚠ REVISED 2026-06-21 — repointed to live sports/esports reward programs.** The Phase-0 gate found reward params ARE exposed (via `/v1/incentives`), but the only live programs are fast in-play sports/esports, not slow markets. See the **REVISION** section of the spec. Net effect on the tasks below: discovery (Task 1) is rebuilt against `/v1/incentives`; the reward contract drops `max_spread`/`min_size` and adds `period`/`program_id`; `model/slowness.py` becomes `model/market_select.py` (select by active-program + book, not slowness); the reward sim uses `discount^ticks` with a `target_size` denominator floor. The controller supplies corrected per-task instructions at dispatch; treat the original task bodies below as superseded where they conflict with the spec revision.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/polybot/clients/us.py` | Modify | add `find_category_markets`, `get_category_resolutions`, `_normalize_reward_market`, `_parse_reward_params` |
| `scripts/probe_rewards_api.py` | Create | Phase-0 probe: dump raw API shapes for category + reward params (throwaway-ish, kept for re-probing) |
| `src/polybot/config.py` | Modify | add `RewardsConfig` + wire into `Settings` |
| `config/settings.yaml` | Modify | add `rewards:` block |
| `src/polybot/storage/db.py` | Modify | add `reward_markets` + `reward_estimates` tables and helpers |
| `src/polybot/model/slowness.py` | Create | adverse-selection-risk classifier (pure) |
| `src/polybot/strategy/market_maker.py` | Modify | add `estimate_reward_range` (pure) |
| `src/polybot/rewards_engine.py` | Create | the cycle loop + `rewards_report` |
| `src/polybot/cli.py` | Modify | add `rewards-gate`, `rewards-run`, `rewards-report` commands |
| `tests/test_slowness.py` | Create | classifier tests |
| `tests/test_reward_range.py` | Create | reward-range tests |
| `tests/test_rewards_engine.py` | Create | engine tests with a fake client + in-memory db |
| `tests/test_us_category.py` | Create | normalizer tests for category discovery |

**Internal contract (used by all tasks below).** Discovery normalizes raw API payloads into this shape. Everything downstream consumes *this*, never the raw API, so the only API-shape-dependent code is `_normalize_reward_market`/`_parse_reward_params` in Task 1:

```python
# A normalized reward-market row:
{
    "token_id": str,          # market slug — the key for books/positions/settlement
    "event_slug": str,
    "category": str,          # "Politics" | "Macro" | "Culture"
    "question": str,
    "end_ts": float | None,   # resolution time, epoch seconds
    "closed": bool,
    "reward": {               # None if the market is NOT reward-eligible
        "pool_usd": float,    # daily reward pool for this market's event
        "discount": float,    # per-tick proximity discount factor
        "target_size": float, # aggregate qualifying size threshold (contracts)
        "max_spread": float,  # max distance from mid that still scores (price units)
        "min_size": float,    # min order size to qualify (contracts)
    } | None,
}
```

---

## Task 1: Phase-0 probe + generic category discovery (the hard gate)

**Files:**
- Create: `scripts/probe_rewards_api.py`
- Modify: `src/polybot/clients/us.py`
- Test: `tests/test_us_category.py`

> Phase 0 is a HARD GATE (spec §3). If the probe shows reward params are NOT exposed by the API, STOP — record the finding in the plan and do not build the rest. The probe code is concrete; the only thing filled in *after* running it is the raw→normalized field mapping inside `_parse_reward_params` (inherent to an unverified API).

- [ ] **Step 1: Write the probe script**

```python
# scripts/probe_rewards_api.py
"""Phase-0 probe: discover whether Polymarket US exposes category markets and
liquidity-reward params via the API. Read-only. Run: `uv run python scripts/probe_rewards_api.py`.

Records nothing automatically — read the printed JSON and fill the field mapping
in clients/us.py:_parse_reward_params from what you see."""

import json

from polybot.clients.us import PolymarketUS

CANDIDATE_QUERIES = ["election", "fed rate", "oscars", "politics", "macro", "culture"]


def _dump(label, payload):
    print(f"\n===== {label} =====")
    text = json.dumps(payload, indent=2, default=str)
    print(text[:4000])
    # surface any reward-shaped keys anywhere in the blob
    hits = [k for k in text.replace('"', " ").split() if "reward" in k.lower() or "spread" in k.lower()]
    if hits:
        print(">>> reward-ish tokens seen:", sorted(set(hits))[:20])


def main():
    client = PolymarketUS.from_env()
    if client is None:
        print("No credentials in .env — set POLYMARKET_KEY_ID / POLYMARKET_SECRET_KEY")
        return
    for q in CANDIDATE_QUERIES:
        try:
            r = client._get("/v1/search", base=client._gateway_url, params={"query": q, "limit": 5})
            _dump(f"/v1/search?query={q} [{r.status_code}]", r.json())
        except Exception as exc:  # noqa: BLE001 — probe, surface everything
            print(f"search {q!r} failed: {exc!r}")
    # probe a markets-list endpoint shape if one exists
    for path in ["/v1/markets", "/v1/rewards", "/v1/incentives/liquidity"]:
        try:
            r = client._get(path, base=client._gateway_url, params={"limit": 3})
            _dump(f"{path} [{r.status_code}]", r.json())
        except Exception as exc:  # noqa: BLE001
            print(f"{path} failed: {exc!r}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the probe and record findings**

Run: `uv run python scripts/probe_rewards_api.py`
Expected: prints JSON for each endpoint. **Read it and confirm:** (a) markets in Politics/Macro/Culture are returned, (b) a reward/spread-shaped object appears on the market or event. Note the exact field names — they fill Step 5.

**GATE:** if no reward params appear anywhere, write a one-paragraph finding at the bottom of this plan file ("Phase 0 result: …") and STOP. Otherwise continue.

- [ ] **Step 3: Write the failing normalizer test**

```python
# tests/test_us_category.py
from polybot.clients.us import _normalize_reward_market, _parse_reward_params


# Synthetic payload in the shape observed by the probe in Step 2.
# (If the probe revealed different key names, update RAW here AND the parser to match.)
RAW = {
    "slug": "fed-cuts-in-july-2026",
    "eventSlug": "fed-july-2026",
    "category": "Macro",
    "title": "Will the Fed cut rates in July 2026?",
    "endDate": "2026-07-31T20:00:00Z",
    "closed": False,
    "rewards": {
        "dailyPoolUsd": 1000.0,
        "discountFactor": 0.30,
        "targetSize": 20000,
        "maxSpread": 0.03,
        "minSize": 50,
    },
}


def test_parse_reward_params_extracts_fields():
    p = _parse_reward_params(RAW)
    assert p == {
        "pool_usd": 1000.0,
        "discount": 0.30,
        "target_size": 20000.0,
        "max_spread": 0.03,
        "min_size": 50.0,
    }


def test_parse_reward_params_none_when_absent():
    assert _parse_reward_params({"slug": "x"}) is None


def test_normalize_reward_market_shape():
    row = _normalize_reward_market(RAW)
    assert row["token_id"] == "fed-cuts-in-july-2026"
    assert row["category"] == "Macro"
    assert row["closed"] is False
    assert row["end_ts"] is not None
    assert row["reward"]["target_size"] == 20000.0
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_us_category.py -v`
Expected: FAIL with `ImportError: cannot import name '_normalize_reward_market'`.

- [ ] **Step 5: Implement the normalizers in `clients/us.py`**

Add near the other pure normalizers (after `_normalize_book`). **Adjust the key names in `_parse_reward_params` to match what the probe printed in Step 2** — the structure below assumes a `rewards` sub-object with `dailyPoolUsd/discountFactor/targetSize/maxSpread/minSize`.

```python
def _parse_reward_params(raw: dict) -> dict | None:
    """Extract normalized liquidity-reward params, or None if not reward-eligible.

    Key names below mirror the probe output (scripts/probe_rewards_api.py); update
    them here if the live API differs. This is the ONLY API-shape-dependent code."""
    rw = raw.get("rewards") if isinstance(raw, dict) else None
    if not rw:
        return None
    try:
        return {
            "pool_usd": float(rw["dailyPoolUsd"]),
            "discount": float(rw["discountFactor"]),
            "target_size": float(rw["targetSize"]),
            "max_spread": float(rw["maxSpread"]),
            "min_size": float(rw["minSize"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _normalize_reward_market(raw: dict) -> dict | None:
    """Map one raw market payload to the internal reward-market contract."""
    slug = raw.get("slug")
    if not slug:
        return None
    end_ts = None
    if raw.get("endDate"):
        end_ts = datetime.fromisoformat(
            raw["endDate"].replace("Z", "+00:00")
        ).timestamp()
    return {
        "token_id": slug,
        "event_slug": raw.get("eventSlug", ""),
        "category": raw.get("category", ""),
        "question": raw.get("title", ""),
        "end_ts": end_ts,
        "closed": bool(raw.get("closed")),
        "reward": _parse_reward_params(raw),
    }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_us_category.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Add the discovery + resolution client methods**

Add to the `PolymarketUS` class (after `get_resolutions`). **Adjust the search path/params to the endpoint the probe confirmed** (this assumes `/v1/search` with a `category` filter; if the probe found `/v1/markets?category=`, use that instead).

```python
    def find_category_markets(self, categories: list[str], limit: int = 100) -> list[dict]:
        """Active reward-eligible markets in the given categories, normalized.

        Returns rows in the internal reward-market contract; only rows with a
        non-None ``reward`` and not ``closed`` are returned."""
        rows: list[dict] = []
        for cat in categories:
            try:
                r = self._get(
                    "/v1/search",
                    base=self._gateway_url,
                    params={"query": cat, "category": cat, "limit": limit},
                )
                r.raise_for_status()
                payload = r.json()
            except (httpx.HTTPError, ValueError):
                continue
            raw_markets = payload.get("markets") or [
                m for ev in payload.get("events", []) for m in (ev.get("markets") or [])
            ]
            for raw in raw_markets:
                row = _normalize_reward_market(raw)
                if row and row["reward"] is not None and not row["closed"]:
                    rows.append(row)
        return rows

    def get_category_resolutions(self, token_ids: list[str]) -> dict[str, int | None]:
        """Resolve outcomes for category markets by slug. None if unresolved.

        Reuses the same single-market endpoint + decisive-price rule as
        get_resolutions, but keyed off a flat token_id list."""
        out: dict[str, int | None] = {}
        for tid in set(token_ids):
            try:
                r = self._get(f"/v1/market/slug/{tid}", base=self._gateway_url)
                if r.status_code != 200:
                    out[tid] = None
                    continue
                payload = r.json()
                market = payload.get("market", payload) if isinstance(payload, dict) else {}
                out[tid] = _parse_resolution(market)
            except (httpx.HTTPError, ValueError):
                out[tid] = None
        return out
```

- [ ] **Step 8: Run the full test file**

Run: `uv run pytest tests/test_us_category.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/probe_rewards_api.py src/polybot/clients/us.py tests/test_us_category.py
git commit -m "feat: generic category discovery + reward params for Polymarket US (Phase 0)"
```

---

## Task 2: RewardsConfig

**Files:**
- Modify: `src/polybot/config.py`
- Modify: `config/settings.yaml`
- Test: `tests/test_us_category.py` (append a config-load assertion)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_us_category.py`:

```python
def test_rewards_config_defaults():
    from polybot.config import RewardsConfig

    c = RewardsConfig()
    assert c.categories == ["Politics", "Macro", "Culture"]
    assert c.max_midpoint_vol > 0
    assert c.min_days_to_resolution >= 1
    assert c.min_snapshots >= 2
    assert 0 < c.opt_competitor_factor <= 1
    assert c.pess_competitor_factor >= 1
    assert c.capital_usd > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_us_category.py::test_rewards_config_defaults -v`
Expected: FAIL with `ImportError: cannot import name 'RewardsConfig'`.

- [ ] **Step 3: Add `RewardsConfig` and wire it into `Settings`**

In `src/polybot/config.py`, add after `QuotingConfig`:

```python
class RewardsConfig(BaseModel):
    """Slow-market liquidity-rewards maker (docs/superpowers/specs/2026-06-21-rewards-mm-simulator-design.md)."""

    categories: list[str] = ["Politics", "Macro", "Culture"]
    capital_usd: float = 300.0            # probe scale ($100-500)
    max_markets: int = 5                  # quote at most N slowest markets
    # slowness / adverse-selection gate
    max_midpoint_vol: float = 0.01        # max realized stdev of mid (price units) to qualify
    min_days_to_resolution: float = 3.0   # avoid markets about to resolve
    min_depth: float = 50.0               # min typical top-of-book depth (contracts)
    min_snapshots: int = 5                # need this many book samples before scoring
    # reward-share uncertainty bounds (spec §6): competitor qualifying size is
    # unobservable, so report a range. opt assumes light competition, pess heavy.
    opt_competitor_factor: float = 0.25   # × observed in-band depth
    pess_competitor_factor: float = 1.0   # × max(target_size, observed depth)
    cycle_seconds: int = 60
    discovery_interval_minutes: int = 30
    db_path: str = "data/rewards.sqlite3"
```

Add to the `Settings` class fields (alongside `quoting`):

```python
    rewards: RewardsConfig = RewardsConfig()
```

- [ ] **Step 4: Add the `rewards:` block to `config/settings.yaml`**

Append at the top level of `config/settings.yaml`:

```yaml
rewards:
  categories: ["Politics", "Macro", "Culture"]
  capital_usd: 300.0
  max_markets: 5
  max_midpoint_vol: 0.01
  min_days_to_resolution: 3.0
  min_depth: 50.0
  min_snapshots: 5
  opt_competitor_factor: 0.25
  pess_competitor_factor: 1.0
  cycle_seconds: 60
  discovery_interval_minutes: 30
  db_path: "data/rewards.sqlite3"
```

- [ ] **Step 5: Run test + full suite to verify nothing broke**

Run: `uv run pytest tests/test_us_category.py -v && uv run pytest -q`
Expected: PASS (config test passes; existing 22 tests still pass).

- [ ] **Step 6: Commit**

```bash
git add src/polybot/config.py config/settings.yaml tests/test_us_category.py
git commit -m "feat: RewardsConfig for slow-market rewards maker"
```

---

## Task 3: Database tables for reward markets + estimates

**Files:**
- Modify: `src/polybot/storage/db.py`
- Test: `tests/test_rewards_engine.py` (created here; extended in Task 6)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rewards_engine.py
from polybot.storage import db


def test_upsert_reward_market_and_read_back():
    conn = db.connect(":memory:")
    row = {
        "token_id": "fed-july", "event_slug": "fed", "category": "Macro",
        "question": "Fed cut?", "end_ts": 1000.0, "closed": False,
        "reward": {"pool_usd": 1000.0, "discount": 0.3, "target_size": 20000.0,
                   "max_spread": 0.03, "min_size": 50.0},
    }
    db.upsert_reward_market(conn, row)
    got = conn.execute("SELECT * FROM reward_markets WHERE token_id='fed-july'").fetchone()
    assert got["category"] == "Macro"
    assert got["pool_usd"] == 1000.0
    assert got["max_spread"] == 0.03


def test_insert_reward_estimate():
    conn = db.connect(":memory:")
    db.insert_reward_estimate(conn, "fed-july", est_opt=2.5, est_pess=0.8)
    got = conn.execute("SELECT * FROM reward_estimates WHERE token_id='fed-july'").fetchone()
    assert got["est_opt"] == 2.5
    assert got["est_pess"] == 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rewards_engine.py -v`
Expected: FAIL with `AttributeError: module 'polybot.storage.db' has no attribute 'upsert_reward_market'`.

- [ ] **Step 3: Add tables to `SCHEMA` and helpers**

In `src/polybot/storage/db.py`, append to the `SCHEMA` string (before the closing `"""`):

```python
CREATE TABLE IF NOT EXISTS reward_markets (
    token_id     TEXT PRIMARY KEY,
    event_slug   TEXT,
    category     TEXT,
    question     TEXT,
    end_ts       REAL,
    closed       INTEGER DEFAULT 0,
    outcome      INTEGER,
    pool_usd     REAL,
    discount     REAL,
    target_size  REAL,
    max_spread   REAL,
    min_size     REAL
);
CREATE TABLE IF NOT EXISTS reward_estimates (
    ts       REAL,
    token_id TEXT,
    est_opt  REAL,
    est_pess REAL
);
CREATE INDEX IF NOT EXISTS idx_rwd_est ON reward_estimates(token_id, ts);
```

Add these functions at the end of the file:

```python
def upsert_reward_market(conn: sqlite3.Connection, row: dict) -> None:
    r = row["reward"] or {}
    conn.execute(
        """INSERT INTO reward_markets
               (token_id, event_slug, category, question, end_ts, closed,
                pool_usd, discount, target_size, max_spread, min_size)
           VALUES (:token_id, :event_slug, :category, :question, :end_ts, :closed,
                   :pool_usd, :discount, :target_size, :max_spread, :min_size)
           ON CONFLICT(token_id) DO UPDATE SET closed=:closed, pool_usd=:pool_usd,
               discount=:discount, target_size=:target_size, max_spread=:max_spread,
               min_size=:min_size""",
        {
            "token_id": row["token_id"], "event_slug": row["event_slug"],
            "category": row["category"], "question": row["question"],
            "end_ts": row["end_ts"], "closed": int(row["closed"]),
            "pool_usd": r.get("pool_usd"), "discount": r.get("discount"),
            "target_size": r.get("target_size"), "max_spread": r.get("max_spread"),
            "min_size": r.get("min_size"),
        },
    )
    conn.commit()


def insert_reward_estimate(conn: sqlite3.Connection, token_id: str,
                           est_opt: float, est_pess: float) -> None:
    conn.execute(
        "INSERT INTO reward_estimates VALUES (?,?,?,?)",
        (time.time(), token_id, est_opt, est_pess),
    )
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rewards_engine.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/polybot/storage/db.py tests/test_rewards_engine.py
git commit -m "feat: reward_markets + reward_estimates tables and helpers"
```

---

## Task 4: Slowness classifier — `model/slowness.py`

**Files:**
- Create: `src/polybot/model/slowness.py`
- Test: `tests/test_slowness.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slowness.py
from polybot.config import RewardsConfig
from polybot.model.slowness import SlownessScore, score_slowness, select_slow_markets

CFG = RewardsConfig()
NOW = 1_000_000.0
FAR_END = NOW + 10 * 86400  # 10 days out


def _snaps(mids, depth=100.0):
    # snapshots: (ts, best_bid, best_ask, bid_depth, ask_depth) with mid = given
    return [(NOW - i * 60, m - 0.01, m + 0.01, depth, depth) for i, m in enumerate(mids)]


def test_stable_market_is_eligible_and_low_risk():
    s = score_slowness("calm", _snaps([0.50] * 6), FAR_END, NOW, CFG)
    assert isinstance(s, SlownessScore)
    assert s.midpoint_vol < 1e-6
    assert s.eligible is True


def test_volatile_market_is_ineligible():
    s = score_slowness("jumpy", _snaps([0.30, 0.55, 0.40, 0.60, 0.35, 0.58]), FAR_END, NOW, CFG)
    assert s.midpoint_vol > CFG.max_midpoint_vol
    assert s.eligible is False


def test_imminent_resolution_is_ineligible():
    soon = NOW + 1 * 86400  # 1 day < min_days_to_resolution (3)
    s = score_slowness("soon", _snaps([0.50] * 6), soon, NOW, CFG)
    assert s.eligible is False


def test_thin_book_is_ineligible():
    s = score_slowness("thin", _snaps([0.50] * 6, depth=10.0), FAR_END, NOW, CFG)
    assert s.eligible is False


def test_too_few_snapshots_is_ineligible():
    s = score_slowness("new", _snaps([0.50, 0.50]), FAR_END, NOW, CFG)  # 2 < min_snapshots (5)
    assert s.eligible is False


def test_select_picks_lowest_risk_first_and_caps_count():
    scored = [
        score_slowness("calm", _snaps([0.50] * 6), FAR_END, NOW, CFG),
        score_slowness("mild", _snaps([0.50, 0.505, 0.50, 0.495, 0.50, 0.50]), FAR_END, NOW, CFG),
        score_slowness("jumpy", _snaps([0.30, 0.60] * 3), FAR_END, NOW, CFG),  # ineligible
    ]
    picked = select_slow_markets(scored, max_markets=1)
    assert picked == ["calm"]  # lowest risk, ineligible excluded, capped at 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_slowness.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polybot.model.slowness'`.

- [ ] **Step 3: Implement `model/slowness.py`**

```python
"""Adverse-selection-risk classifier for reward-market selection.

The slow-market thesis (spec §5): earn liquidity rewards where surprises — and
therefore fills against us — are rare. A market is a good quoting target when its
midpoint barely moves, it resolves far in the future, and its book is deep enough
to rest qualifying size. Pure functions; the engine feeds in stored book history."""

import statistics
from dataclasses import dataclass

from polybot.config import RewardsConfig


@dataclass
class SlownessScore:
    token_id: str
    midpoint_vol: float        # realized stdev of mid over the window (price units)
    days_to_resolution: float
    typical_depth: float       # median of per-snapshot min(bid_depth, ask_depth)
    n_snapshots: int
    risk: float                # composite; lower = slower = better
    eligible: bool


def score_slowness(
    token_id: str,
    snapshots: list[tuple],     # (ts, best_bid, best_ask, bid_depth, ask_depth)
    end_ts: float | None,
    now: float,
    cfg: RewardsConfig,
) -> SlownessScore:
    """Score one market's adverse-selection risk from recent book snapshots."""
    usable = [
        s for s in snapshots
        if s[1] is not None and s[2] is not None
    ]
    n = len(usable)
    mids = [(s[1] + s[2]) / 2 for s in usable]
    depths = [min(s[3] or 0.0, s[4] or 0.0) for s in usable]
    vol = statistics.pstdev(mids) if len(mids) >= 2 else float("inf")
    typical_depth = statistics.median(depths) if depths else 0.0
    days = (end_ts - now) / 86400.0 if end_ts is not None else 0.0

    eligible = (
        n >= cfg.min_snapshots
        and vol <= cfg.max_midpoint_vol
        and days >= cfg.min_days_to_resolution
        and typical_depth >= cfg.min_depth
    )
    # composite risk: volatility dominates; shrink-to-resolution adds a small penalty.
    risk = vol + (1.0 / max(days, 0.5)) * cfg.max_midpoint_vol
    return SlownessScore(
        token_id=token_id, midpoint_vol=vol, days_to_resolution=days,
        typical_depth=typical_depth, n_snapshots=n, risk=risk, eligible=eligible,
    )


def select_slow_markets(scored: list[SlownessScore], max_markets: int) -> list[str]:
    """Token ids of the lowest-risk eligible markets, capped at max_markets."""
    eligible = sorted((s for s in scored if s.eligible), key=lambda s: s.risk)
    return [s.token_id for s in eligible[:max_markets]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_slowness.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/polybot/model/slowness.py tests/test_slowness.py
git commit -m "feat: slowness classifier for adverse-selection-aware market selection"
```

---

## Task 5: Optimistic/pessimistic reward range

**Files:**
- Modify: `src/polybot/strategy/market_maker.py`
- Test: `tests/test_reward_range.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reward_range.py
from polybot.strategy.market_maker import MMQuote, estimate_reward_range

BOOK = {"best_bid": 0.49, "best_ask": 0.51, "bid_depth": 100, "ask_depth": 100}
PARAMS = {"pool_usd": 1000.0, "discount": 0.10, "target_size": 20000.0,
          "max_spread": 0.03, "min_size": 50.0}
QUOTES = [MMQuote("t", "BUY", 0.49, 200), MMQuote("t", "SELL", 0.51, 200)]


def test_range_pessimistic_le_optimistic_and_nonneg():
    opt, pess = estimate_reward_range(QUOTES, BOOK, PARAMS, seconds=86400,
                                      opt_factor=0.25, pess_factor=1.0)
    assert opt >= pess >= 0.0


def test_single_sided_scores_zero_both_bounds():
    one = [MMQuote("t", "BUY", 0.49, 200)]
    opt, pess = estimate_reward_range(one, BOOK, PARAMS, seconds=86400,
                                      opt_factor=0.25, pess_factor=1.0)
    assert opt == 0.0 and pess == 0.0


def test_pessimistic_uses_target_size_as_competition_floor():
    # With a huge target_size, the pessimistic share (hence reward) is tiny.
    big = {**PARAMS, "target_size": 1_000_000.0}
    _, pess = estimate_reward_range(QUOTES, BOOK, big, seconds=86400,
                                    opt_factor=0.25, pess_factor=1.0)
    assert pess < 1.0


def test_reward_scales_with_time():
    full, _ = estimate_reward_range(QUOTES, BOOK, PARAMS, 86400, 0.25, 1.0)
    half, _ = estimate_reward_range(QUOTES, BOOK, PARAMS, 43200, 0.25, 1.0)
    assert abs(half - full / 2) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reward_range.py -v`
Expected: FAIL with `ImportError: cannot import name 'estimate_reward_range'`.

- [ ] **Step 3: Implement `estimate_reward_range` in `strategy/market_maker.py`**

Add at the end of the file (it reuses the existing `estimate_reward`):

```python
def _in_band_depth(book: dict, max_spread: float) -> float:
    """Observed resting depth within max_spread of mid — our proxy for the
    competing qualifying size we can actually see on the public book."""
    bb, ba = book.get("best_bid"), book.get("best_ask")
    if bb is None or ba is None:
        return 0.0
    mid = (bb + ba) / 2
    depth = 0.0
    for px, qty in book.get("bids", []):
        if mid - px <= max_spread:
            depth += qty
    for px, qty in book.get("asks", []):
        if px - mid <= max_spread:
            depth += qty
    # fall back to top-of-book depth if the ladder wasn't provided
    if depth == 0.0:
        depth = (book.get("bid_depth", 0.0) or 0.0) + (book.get("ask_depth", 0.0) or 0.0)
    return depth


def estimate_reward_range(
    quotes: list[MMQuote],
    book: dict,
    params: dict,
    seconds: float,
    opt_factor: float,
    pess_factor: float,
) -> tuple[float, float]:
    """(optimistic, pessimistic) reward estimate for a two-sided quote.

    The competing qualifying size is unobservable (spec §6), so we bracket it:
      - optimistic: competitors = observed in-band depth × opt_factor (light competition)
      - pessimistic: competitors = max(target_size, in-band depth) × pess_factor (heavy)
    Both bounds reuse estimate_reward; returns (opt, pess) with opt >= pess >= 0."""
    pool = params["pool_usd"]
    discount = params["discount"]
    observed = _in_band_depth(book, params["max_spread"])
    opt_comp = observed * opt_factor
    pess_comp = max(params["target_size"], observed) * pess_factor
    opt = estimate_reward(quotes, book, pool, discount, opt_comp, seconds)
    pess = estimate_reward(quotes, book, pool, discount, pess_comp, seconds)
    return max(opt, pess), min(opt, pess)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reward_range.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/polybot/strategy/market_maker.py tests/test_reward_range.py
git commit -m "feat: optimistic/pessimistic reward range for the share-uncertainty bound"
```

---

## Task 6: The rewards engine — `rewards_engine.py`

**Files:**
- Create: `src/polybot/rewards_engine.py`
- Test: `tests/test_rewards_engine.py` (extend)

The engine is decoupled from weather (no forecasts/lock). It reuses `execution/paper.py` (fills, settlement, inventory) and `strategy/market_maker.py` (`maker_quotes` with `model_prob=None`, `estimate_reward_range`). It is injected with a client object so tests use a fake.

- [ ] **Step 1: Write the failing test (extend `tests/test_rewards_engine.py`)**

```python
from polybot.config import load_settings
from polybot.rewards_engine import RewardsEngine, rewards_report
from polybot.storage import db


class FakeClient:
    """Stand-in for PolymarketUS: fixed market list, stable book, no resolution."""

    def __init__(self, rows, book):
        self._rows = rows
        self._book = book

    def find_category_markets(self, categories, limit=100):
        return self._rows

    def get_order_book(self, token_id):
        return dict(self._book)

    def get_category_resolutions(self, token_ids):
        return {t: None for t in token_ids}


def _market(tid):
    return {
        "token_id": tid, "event_slug": "ev", "category": "Macro",
        "question": f"q-{tid}", "end_ts": 9_999_999_999.0, "closed": False,
        "reward": {"pool_usd": 1000.0, "discount": 0.10, "target_size": 20000.0,
                   "max_spread": 0.03, "min_size": 50.0},
    }


STABLE_BOOK = {"best_bid": 0.49, "best_ask": 0.51, "bid_depth": 100, "ask_depth": 100,
               "bids": [[0.49, 100]], "asks": [[0.51, 100]]}


def test_engine_warms_up_then_quotes_and_estimates_reward():
    settings = load_settings()
    settings.rewards.min_snapshots = 3
    settings.rewards.min_depth = 50.0
    eng = RewardsEngine(settings, client=FakeClient([_market("m1")], STABLE_BOOK),
                        db_path=":memory:")
    eng.discover()
    # First cycles only accumulate snapshots (insufficient history -> no quotes).
    for _ in range(2):
        s = eng.cycle()
    assert s["quotes"] == 0
    # After enough snapshots, the stable market becomes eligible and gets quoted.
    for _ in range(3):
        s = eng.cycle()
    assert s["selected"] == 1
    assert s["quotes"] == 2  # two-sided
    assert s["reward_opt"] >= s["reward_pess"] >= 0.0

    rep = rewards_report(eng.conn)
    assert rep["reward_opt"] >= rep["reward_pess"] >= 0.0
    assert "net_opt" in rep and "net_pess" in rep


def test_engine_skips_volatile_market():
    settings = load_settings()
    settings.rewards.min_snapshots = 3

    class JumpyClient(FakeClient):
        def __init__(self):
            super().__init__([_market("vol")], STABLE_BOOK)
            self._n = 0

        def get_order_book(self, token_id):
            self._n += 1
            mid = 0.30 if self._n % 2 else 0.60  # wild swings
            return {"best_bid": mid - 0.01, "best_ask": mid + 0.01,
                    "bid_depth": 100, "ask_depth": 100,
                    "bids": [[mid - 0.01, 100]], "asks": [[mid + 0.01, 100]]}

    eng = RewardsEngine(settings, client=JumpyClient(), db_path=":memory:")
    eng.discover()
    for _ in range(6):
        s = eng.cycle()
    assert s["selected"] == 0  # volatility keeps it ineligible
    assert s["quotes"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rewards_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polybot.rewards_engine'`.

- [ ] **Step 3: Implement `src/polybot/rewards_engine.py`**

```python
"""Paper rewards-MM engine for slow Polymarket US markets (approach B).

Decoupled from the weather machinery: no forecasts, no lock state. Each cycle
snapshots books for discovered category markets, scores their adverse-selection
risk from accumulated snapshots, quotes the slowest few two-sided via the
existing market_maker policy (fair value = book mid, model_prob=None), and
accrues an optimistic/pessimistic reward range. Reuses execution/paper.py for
simulated fills, inventory, and settlement. Writes to data/rewards.sqlite3."""

import time

from rich.console import Console

from polybot.clients.us import PolymarketUS
from polybot.config import ROOT, Settings
from polybot.execution import paper
from polybot.model import slowness
from polybot.storage import db
from polybot.strategy import market_maker as mm

console = Console()


class RewardsEngine:
    def __init__(self, settings: Settings, client=None, db_path: str | None = None):
        self.s = settings
        self.r = settings.rewards
        self.client = client if client is not None else PolymarketUS.from_env()
        if self.client is None:
            raise RuntimeError("Polymarket US credentials required (set them in .env)")
        path = db_path or str(ROOT / self.r.db_path)
        self.conn = db.connect(path)
        self.markets: dict[str, dict] = {}   # token_id -> reward-market row
        self.last_discovery = 0.0

    def discover(self) -> None:
        rows = self.client.find_category_markets(self.r.categories)
        for row in rows:
            self.markets[row["token_id"]] = row
            db.upsert_reward_market(self.conn, row)
        self.last_discovery = time.time()
        console.log(f"discovery: {len(self.markets)} reward markets tracked")

    def _recent_snapshots(self, token_id: str, limit: int = 60) -> list[tuple]:
        rows = self.conn.execute(
            "SELECT ts, best_bid, best_ask, bid_depth, ask_depth FROM book_snapshots"
            " WHERE token_id=? ORDER BY ts DESC LIMIT ?",
            (token_id, limit),
        ).fetchall()
        return [(r["ts"], r["best_bid"], r["best_ask"], r["bid_depth"], r["ask_depth"]) for r in rows]

    def cycle(self) -> dict:
        now = time.time()
        if now - self.last_discovery > self.r.discovery_interval_minutes * 60:
            self.discover()

        stats = {"books": 0, "selected": 0, "quotes": 0, "fills": 0,
                 "reward_opt": 0.0, "reward_pess": 0.0, "settled": 0}

        # 1. snapshot every tracked market (builds the history slowness needs)
        for tid in list(self.markets):
            book = self.client.get_order_book(tid)
            if book is None:
                continue
            stats["books"] += 1
            db.insert_snapshot(self.conn, tid, book)
            stats["fills"] += paper.check_maker_fills(self.conn, tid, book, self.s.quoting)

        # 2. score slowness and pick the slowest eligible markets
        scored = [
            slowness.score_slowness(
                tid, self._recent_snapshots(tid), self.markets[tid]["end_ts"], now, self.r
            )
            for tid in self.markets
        ]
        selected = slowness.select_slow_markets(scored, self.r.max_markets)
        stats["selected"] = len(selected)

        # 3. quote the selected markets; estimate reward range; rest the quotes
        for tid in selected:
            book = self.client.get_order_book(tid)
            if book is None:
                continue
            inv = paper.position_qty(self.conn, tid)
            quotes = mm.maker_quotes(tid, None, book, self.s.quoting, inv, locked=False)
            paper.refresh_maker_orders(self.conn, tid, quotes, 0.0)
            if not quotes:
                continue
            stats["quotes"] += len(quotes)
            opt, pess = mm.estimate_reward_range(
                quotes, book, self.markets[tid]["reward"], self.r.cycle_seconds,
                self.r.opt_competitor_factor, self.r.pess_competitor_factor,
            )
            db.insert_reward_estimate(self.conn, tid, opt, pess)
            stats["reward_opt"] += opt
            stats["reward_pess"] += pess
        self.conn.commit()

        stats["settled"] = self._settle_resolved()
        return stats

    def _settle_resolved(self) -> int:
        held = [r["token_id"] for r in self.conn.execute(
            "SELECT token_id FROM positions WHERE qty != 0"
            " AND token_id NOT IN (SELECT token_id FROM settlements)"
        ).fetchall()]
        if not held:
            return 0
        outcomes = self.client.get_category_resolutions(held)
        settled = 0
        for tid, outcome in outcomes.items():
            if outcome is None:
                continue
            paper.settle_market(self.conn, tid, outcome)
            self.conn.execute(
                "UPDATE reward_markets SET closed=1, outcome=? WHERE token_id=?", (outcome, tid)
            )
            self.conn.commit()
            self.markets.pop(tid, None)
            settled += 1
        return settled

    def run(self, cycles: int | None = None) -> None:
        self.discover()
        n = 0
        while cycles is None or n < cycles:
            started = time.time()
            try:
                s = self.cycle()
                console.log(
                    f"cycle {n}: books={s['books']} selected={s['selected']} "
                    f"quotes={s['quotes']} fills={s['fills']} "
                    f"reward=[{s['reward_pess']:.3f}..{s['reward_opt']:.3f}] settled={s['settled']}"
                )
            except Exception as exc:  # never die mid-loop
                console.log(f"[red]cycle error: {exc!r}[/red]")
            n += 1
            if cycles is None or n < cycles:
                time.sleep(max(1.0, self.r.cycle_seconds - (time.time() - started)))


def rewards_report(conn) -> dict:
    """Net = reward range − adverse-selection − fees (spec §9). Reports both
    bounds; the go/no-go gate requires net_pess > 0 over several days."""
    est = conn.execute(
        "SELECT COALESCE(SUM(est_opt),0) o, COALESCE(SUM(est_pess),0) p FROM reward_estimates"
    ).fetchone()
    realized = conn.execute("SELECT COALESCE(SUM(realized_pnl),0) v FROM positions").fetchone()["v"]
    settle = conn.execute("SELECT COALESCE(SUM(pnl),0) v FROM settlements WHERE qty!=0").fetchone()["v"]
    fills = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(fee),0) f FROM paper_fills").fetchone()
    open_pos = conn.execute(
        """SELECT p.qty, p.avg_cost,
                  (SELECT best_bid FROM book_snapshots b WHERE b.token_id=p.token_id
                   ORDER BY ts DESC LIMIT 1) mark
           FROM positions p WHERE p.qty != 0"""
    ).fetchall()
    unreal = sum(r["qty"] * ((r["mark"] or r["avg_cost"]) - r["avg_cost"]) for r in open_pos)
    adverse = realized + unreal  # inventory PnL (settlement + open mark) net of fees in realized
    return {
        "reward_opt": est["o"],
        "reward_pess": est["p"],
        "adverse_selection_pnl": settle,
        "unrealized": unreal,
        "fees_paid": fills["f"],
        "net_opt": est["o"] + adverse,
        "net_pess": est["p"] + adverse,
        "fills": fills["n"],
        "open_positions": len(open_pos),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rewards_engine.py -v`
Expected: PASS (4 tests: the 2 db tests from Task 3 + 2 engine tests).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (existing 22 + all new tests).

- [ ] **Step 6: Commit**

```bash
git add src/polybot/rewards_engine.py tests/test_rewards_engine.py
git commit -m "feat: RewardsEngine — slow-market rewards-MM paper simulator"
```

---

## Task 7: CLI commands (`rewards-gate`, `rewards-run`, `rewards-report`)

**Files:**
- Modify: `src/polybot/cli.py`

- [ ] **Step 1: Add the three commands**

In `src/polybot/cli.py`, add after the `maker_report_cmd` command:

```python
@app.command(name="rewards-gate")
def rewards_gate():
    """Phase-0 gate: confirm Polymarket US exposes category markets + reward params."""
    from polybot.clients.us import PolymarketUS

    settings = load_settings()
    client = PolymarketUS.from_env()
    if client is None:
        rprint("[red]No credentials — set POLYMARKET_KEY_ID / POLYMARKET_SECRET_KEY in .env[/red]")
        raise typer.Exit(1)
    rows = client.find_category_markets(settings.rewards.categories)
    eligible = [r for r in rows if r["reward"] is not None]
    rprint(f"[bold]{len(rows)}[/bold] category markets, "
           f"[bold]{len(eligible)}[/bold] reward-eligible across {settings.rewards.categories}")
    if not eligible:
        rprint("[red]GATE FAILED: no reward params exposed. Do not proceed (spec §3).[/red]")
        raise typer.Exit(1)
    t = Table(title="Reward-eligible markets (sample)")
    for col in ("category", "question", "pool$", "max_spread", "target_size"):
        t.add_column(col)
    for r in eligible[:15]:
        rw = r["reward"]
        t.add_row(r["category"], r["question"][:50], f"{rw['pool_usd']:.0f}",
                  f"{rw['max_spread']:.3f}", f"{rw['target_size']:.0f}")
    rprint(t)
    rprint("[green]GATE PASSED.[/green]")


@app.command(name="rewards-run")
def rewards_run(cycles: int = typer.Option(None, help="Stop after N cycles (default: forever)")):
    """Run the slow-market rewards-MM paper simulator."""
    from polybot.rewards_engine import RewardsEngine

    RewardsEngine(load_settings()).run(cycles=cycles)


@app.command(name="rewards-report")
def rewards_report_cmd():
    """Net = reward range − adverse selection − fees for the rewards-MM run."""
    from polybot.config import ROOT
    from polybot.rewards_engine import rewards_report
    from polybot.storage import db

    settings = load_settings()
    conn = db.connect(str(ROOT / settings.rewards.db_path))
    r = rewards_report(conn)
    rprint(f"[bold]Reward income (est):[/bold] "
           f"${r['reward_pess']:+.2f} .. ${r['reward_opt']:+.2f}  [dim](pess..opt)[/dim]")
    rprint(f"[bold]Adverse selection (settle):[/bold] ${r['adverse_selection_pnl']:+.2f}")
    rprint(f"[bold]Unrealized:[/bold]               ${r['unrealized']:+.2f}")
    rprint(f"[bold]Fees paid:[/bold]                ${r['fees_paid']:+.3f}")
    rprint(f"[bold cyan]NET:[/bold cyan] ${r['net_pess']:+.2f} .. ${r['net_opt']:+.2f}")
    rprint(f"[dim]fills={r['fills']} open_positions={r['open_positions']}[/dim]")
    if r["net_pess"] > 0:
        rprint("[green]Pessimistic net > 0 — go/no-go gate would pass for this period.[/green]")
    else:
        rprint("[yellow]Pessimistic net <= 0 — gate not met yet.[/yellow]")
```

- [ ] **Step 2: Verify the CLI registers (smoke test)**

Run: `uv run polybot --help`
Expected: lists `rewards-gate`, `rewards-run`, `rewards-report` among the commands.

Run: `uv run polybot rewards-report`
Expected: prints a zeroed report (no data yet) without error — confirms the wiring and the fresh `data/rewards.sqlite3` schema.

- [ ] **Step 3: Run the Phase-0 gate against the live API**

Run: `uv run polybot rewards-gate`
Expected: either "GATE PASSED" with a table of reward-eligible markets, or "GATE FAILED". **If FAILED, stop and record the finding** — the simulator can't be trusted without reward params.

- [ ] **Step 4: Commit**

```bash
git add src/polybot/cli.py
git commit -m "feat: rewards-gate / rewards-run / rewards-report CLI commands"
```

---

## Task 8: First validation run + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run a bounded simulation**

Run: `uv run polybot rewards-run --cycles 20`
Expected: cycles log `selected=` and `reward=[pess..opt]`; no crashes. (Early cycles show `selected=0` during snapshot warmup — that is correct per `min_snapshots`.)

- [ ] **Step 2: Inspect the report**

Run: `uv run polybot rewards-report`
Expected: a reward range, adverse-selection, fees, and a NET range. Record whether `net_pess > 0`.

- [ ] **Step 3: Document the new mode in `README.md`**

Add a row to the Status table and a Usage entry:

```markdown
| Rewards-MM simulator (slow Politics/Macro/Culture markets) | **new** — see `docs/superpowers/specs/2026-06-21-rewards-mm-simulator-design.md` |
```

```bash
uv run polybot rewards-gate     # Phase-0: confirm reward params exposed
uv run polybot rewards-run      # simulate rewards-MM on slow markets
uv run polybot rewards-report   # net = reward range − adverse selection − fees
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document the rewards-MM simulator mode"
```

---

## Phase 0 result: GATE FAILED (2026-06-21)

Ran `scripts/probe_rewards_api.py` against the live gateway (`gateway.polymarket.us`) with valid credentials. **The API does NOT expose any liquidity-reward params.** Findings:

- `/v1/search?query={politics,macro,election,fed rate,oscars,culture}` all return `200` with `events[].markets[]` carrying a real `category` field (`"politics"`, `"macro"`, `"sports"`, etc.) — so category discovery itself is viable. Politics and Macro events are returned (e.g. "Nevada Governor Election Winner" category `politics`, "June Unemployment Rate" category `macro`).
- **No reward object anywhere.** An exhaustive walk of all 109 distinct keys across every search + `/v1/markets` payload surfaced only `feeCoefficient` (a *trading fee*, e.g. 0.05), `mainSpreadLine` (sports point-spread line), `orderPriceMinTickSize`, and `ticker`. No `rewards`, `dailyPoolUsd`/`pool_usd`, `targetSize`, `maxSpread` (maker), `minSize`, `discountFactor`, or any incentive/liquidity/maker/rebate field exists on events or markets.
- The dedicated endpoints `/v1/rewards` and `/v1/incentives/liquidity` both return **404** (`{"code":5,"message":"The server was unable to process your request."}`).
- The only "spread"/"reward"-ish tokens in the blobs are sports betting terms (`SPORTS_MARKET_TYPE_SPREAD`, `game-lines/spread/*`, `soccer_team_*_spread`), unrelated to liquidity rewards.

**Conclusion (spec §3 hard gate):** the $1,000/day/event reward pool params the simulator needs are not observable via this API. The normalizers (`_parse_reward_params`/`_normalize_reward_market`) and discovery methods were still implemented and unit-tested against the assumed/synthetic shape (the contract is correct), but `find_category_markets` will return **zero** reward-eligible rows against the live API because every market's `_parse_reward_params` yields `None`. **Tasks 2–8 are BLOCKED** until either (a) the reward params are exposed via an authenticated/different endpoint we haven't found, or (b) reward params are sourced out-of-band (docs/manual config) and the contract is fed from there instead of the API. Do not build the rest of the simulator assuming reward fields exist on the public payloads.

---

## Self-Review notes

- **Spec coverage:** §3 Phase-0 gate → Task 1 + `rewards-gate` (Task 7). §4 components → reused (`market_maker.py`, `paper.py`, `db.py`) + new (`slowness.py` Task 4, `rewards_engine.py` Task 6). §5 market selection → Task 4. §6 reward sim + **share range** → Task 5 (`estimate_reward_range`) reusing the existing `estimate_reward`. §7 quoting policy → reuses `maker_quotes(model_prob=None)`. §8 adverse-selection accounting → `paper.check_maker_fills`/`settle_market`, surfaced in `rewards_report`. §9 reporting/go-no-go → Task 7 `rewards-report` (`net_pess > 0` gate). §10 testing → Tasks 1,4,5,6. §11 out-of-scope (no live orders) → engine is read-only + paper only.
- **Reuse over rebuild:** the spec named `reward_sim.py`/`rewards_maker.py` as new files; in implementation the equivalent logic already lives in `strategy/market_maker.py`, so we extend it (per writing-plans: follow existing patterns, don't restructure). The spec's intent is fully met.
- **API uncertainty:** the only API-shape-dependent code is `_parse_reward_params`/`_normalize_reward_market` (Task 1), explicitly gated by the probe; everything downstream consumes the fixed internal contract.
- **Type consistency:** `MMQuote(token_id, side, price, size)` used consistently; `estimate_reward_range(quotes, book, params, seconds, opt_factor, pess_factor) -> (opt, pess)`; reward-market contract dict keys match across `clients/us.py`, `db.upsert_reward_market`, `slowness`, and the engine.
