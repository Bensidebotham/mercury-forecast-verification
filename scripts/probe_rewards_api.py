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
