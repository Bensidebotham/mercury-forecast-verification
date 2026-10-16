"""Live (pre-settlement) views: where the model currently disagrees with the market,
plus a tracking summary. Uses the latest live snapshot per open market."""
import time

from sqlalchemy import Engine

from weather_vs_market.storage import store


def current_disagreements(engine: Engine, model: str, limit: int = 25, now: float | None = None,
                          min_lead_hours: float = 1.0) -> list[dict]:
    now = now if now is not None else time.time()
    open_markets = [m for m in store.read_markets(engine, store.vmarket.c.settled == 0)
                    if m["close_ts"] is not None and (m["close_ts"] - now) / 3600 >= min_lead_hours]
    uids = [m["market_uid"] for m in open_markets]
    quotes = store.latest_by_market(engine, store.vquote, "market_prob", uids,
                                    store.vquote.c.source == "live")
    preds = store.latest_by_market(engine, store.vpred, "model_prob", uids,
                                   store.vpred.c.model == model)
    out = []
    for m in open_markets:
        uid = m["market_uid"]
        if uid not in quotes or uid not in preds:
            continue
        model_p, market_p = preds[uid][1], quotes[uid][1]
        out.append({
            "market_uid": uid, "venue": m["venue"], "city": m["city"],
            "target_date": m["target_date"], "question": m["question"],
            "bucket_lo": m["bucket_lo"], "bucket_hi": m["bucket_hi"],
            "model_prob": round(model_p, 4), "market_prob": round(market_p, 4),
            "gap": round(model_p - market_p, 4),
            "lead_hours": round((m["close_ts"] - now) / 3600.0, 1),
        })
    out.sort(key=lambda r: abs(r["gap"]), reverse=True)
    return out[:limit]


def tracking_summary(engine: Engine) -> dict:
    v, q, p = store.vmarket, store.vquote, store.vpred
    runs = store.read_runs(engine, limit=1)
    return {
        "n_markets": store.count(engine, v),
        "n_open": store.count(engine, v, v.c.settled == 0),
        "n_settled": store.count(engine, v, v.c.settled == 1),
        "n_live_quotes": store.count(engine, q, q.c.source == "live"),
        "n_preds": store.count(engine, p),
        "last_run": runs[0] if runs else None,
    }
