"""Local web dashboard for the paper-trading book.

Zero dependencies: stdlib http.server + one inline HTML page that polls
/api/state every 30s. A background thread records an equity snapshot
every 5 minutes so the equity curve fills in even when no browser is
open. Run: `polybot dashboard` -> http://127.0.0.1:8787
"""

import json
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from polybot.config import Settings

SNAPSHOT_EVERY = 300  # seconds


def _conn(db_path: str) -> sqlite3.Connection:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


def compute_state(db_path: str, bankroll: float) -> dict:
    conn = _conn(db_path)
    try:
        realized = conn.execute(
            "SELECT COALESCE(SUM(realized_pnl),0) v FROM positions"
        ).fetchone()["v"]
        positions = [
            dict(r)
            for r in conn.execute(
                """SELECT p.token_id, p.qty, p.avg_cost, p.realized_pnl,
                          m.question, m.city, m.target_date,
                          (SELECT best_bid FROM book_snapshots b
                           WHERE b.token_id=p.token_id ORDER BY ts DESC LIMIT 1) AS mark,
                          (SELECT prob FROM model_probs mp
                           WHERE mp.token_id=p.token_id ORDER BY ts DESC LIMIT 1) AS model_prob
                   FROM positions p LEFT JOIN markets m ON m.token_id=p.token_id
                   WHERE p.qty != 0 ORDER BY m.city, m.target_date"""
            ).fetchall()
        ]
        for p in positions:
            mark = p["mark"] if p["mark"] is not None else p["avg_cost"]
            p["mark"] = mark
            p["upnl"] = p["qty"] * (mark - p["avg_cost"])
            p["cost"] = p["qty"] * p["avg_cost"]
        unrealized = sum(p["upnl"] for p in positions)
        fills = [
            dict(r)
            for r in conn.execute(
                """SELECT f.ts, f.side, f.kind, f.price, f.size, f.fee, f.model_prob,
                          m.question, m.city, m.target_date
                   FROM paper_fills f LEFT JOIN markets m ON m.token_id=f.token_id
                   ORDER BY f.ts DESC LIMIT 25"""
            ).fetchall()
        ]
        settlements = [
            dict(r)
            for r in conn.execute(
                """SELECT s.ts, s.outcome, s.qty, s.pnl, m.question, m.city, m.target_date
                   FROM settlements s LEFT JOIN markets m ON m.token_id=s.token_id
                   WHERE s.qty != 0 ORDER BY s.ts DESC LIMIT 25"""
            ).fetchall()
        ]
        history = [
            [r["ts"], r["equity"]]
            for r in conn.execute(
                "SELECT ts, equity FROM equity_snapshots ORDER BY ts"
            ).fetchall()
        ]
        counts = dict(
            conn.execute(
                """SELECT 'fills' k, COUNT(*) v FROM paper_fills
                   UNION SELECT 'open_orders', COUNT(*) FROM paper_orders WHERE status='open'
                   UNION SELECT 'markets', COUNT(*) FROM markets WHERE closed=0
                   UNION SELECT 'snapshots', COUNT(*) FROM book_snapshots"""
            ).fetchall()
        )
        last_snap = conn.execute("SELECT MAX(ts) v FROM book_snapshots").fetchone()["v"]
        return {
            "ts": time.time(),
            "bankroll": bankroll,
            "realized": realized,
            "unrealized": unrealized,
            "equity": bankroll + realized + unrealized,
            "positions": positions,
            "fills": fills,
            "settlements": settlements,
            "equity_history": history,
            "counts": counts,
            "last_snapshot_ts": last_snap,
        }
    finally:
        conn.close()


def record_equity(db_path: str, bankroll: float) -> None:
    state = compute_state(db_path, bankroll)
    conn = _conn(db_path)
    try:
        last = conn.execute("SELECT MAX(ts) v FROM equity_snapshots").fetchone()["v"]
        if last is None or time.time() - last >= SNAPSHOT_EVERY - 5:
            conn.execute(
                "INSERT INTO equity_snapshots VALUES (?,?,?,?)",
                (time.time(), state["realized"], state["unrealized"], state["equity"]),
            )
            conn.commit()
    finally:
        conn.close()


def _snapshot_loop(db_path: str, bankroll: float) -> None:
    while True:
        try:
            record_equity(db_path, bankroll)
        except Exception:
            pass
        time.sleep(SNAPSHOT_EVERY)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>polybot — paper book</title>
<style>
  :root { --bg:#0d1117; --panel:#161b22; --line:#21262d; --text:#e6edf3;
          --dim:#8b949e; --green:#3fb950; --red:#f85149; --accent:#58a6ff; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--text);
         font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; padding:24px; }
  h1 { font-size:16px; letter-spacing:.04em; margin-bottom:4px; }
  .sub { color:var(--dim); font-size:12px; margin-bottom:20px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
           gap:12px; margin-bottom:20px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:8px;
          padding:14px 16px; }
  .card .k { color:var(--dim); font-size:11px; text-transform:uppercase;
             letter-spacing:.08em; }
  .card .v { font-size:22px; margin-top:4px; font-variant-numeric:tabular-nums; }
  .pos { color:var(--green); } .neg { color:var(--red); }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px;
           padding:16px; margin-bottom:20px; }
  .panel h2 { font-size:12px; color:var(--dim); text-transform:uppercase;
              letter-spacing:.08em; margin-bottom:10px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { text-align:left; color:var(--dim); font-weight:normal; font-size:11px;
       text-transform:uppercase; letter-spacing:.06em; padding:4px 8px;
       border-bottom:1px solid var(--line); }
  td { padding:5px 8px; border-bottom:1px solid var(--line);
       font-variant-numeric:tabular-nums; white-space:nowrap; }
  td.q { white-space:normal; color:var(--text); max-width:420px; }
  tr:last-child td { border-bottom:none; }
  #chart { width:100%; height:160px; }
  .stale { color:var(--red); }
  .ok { color:var(--green); }
</style></head>
<body>
<h1>polybot — paper book</h1>
<div class="sub" id="status">loading…</div>
<div class="cards" id="cards"></div>
<div class="panel"><h2>Equity ($)</h2><svg id="chart" preserveAspectRatio="none"></svg></div>
<div class="panel"><h2>Open positions</h2><div id="positions"></div></div>
<div class="panel"><h2>Settlements</h2><div id="settlements"></div></div>
<div class="panel"><h2>Recent fills</h2><div id="fills"></div></div>
<script>
const fmt = (x, d=2) => x==null ? "—" : Number(x).toFixed(d);
const money = x => (x>=0?"+$":"-$") + Math.abs(x).toFixed(2);
const cls = x => x>=0 ? "pos" : "neg";
const tdate = ts => new Date(ts*1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});

function card(k, v, klass="") {
  return `<div class="card"><div class="k">${k}</div><div class="v ${klass}">${v}</div></div>`;
}

function table(rows, cols) {
  if (!rows.length) return '<div style="color:var(--dim)">none yet</div>';
  const head = cols.map(c=>`<th>${c.h}</th>`).join("");
  const body = rows.map(r=>"<tr>"+cols.map(c=>`<td class="${c.c?c.c(r):''}">${c.f(r)}</td>`).join("")+"</tr>").join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function drawChart(hist, bankroll) {
  const svg = document.getElementById("chart");
  const W = svg.clientWidth, H = svg.clientHeight;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  if (hist.length < 2) { svg.innerHTML =
    `<text x="10" y="20" fill="#8b949e" font-size="12">equity curve appears after a few snapshots (every 5 min)</text>`; return; }
  const xs = hist.map(h=>h[0]), ys = hist.map(h=>h[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys, bankroll), y1 = Math.max(...ys, bankroll);
  const pad = Math.max(0.5, (y1-y0)*0.1); y0-=pad; y1+=pad;
  const X = t => (t-x0)/(x1-x0||1)*(W-20)+10;
  const Y = v => H-10-(v-y0)/(y1-y0||1)*(H-20);
  const path = hist.map((h,i)=>(i?"L":"M")+X(h[0]).toFixed(1)+","+Y(h[1]).toFixed(1)).join(" ");
  const base = Y(bankroll);
  const last = ys[ys.length-1];
  svg.innerHTML =
    `<line x1="10" x2="${W-10}" y1="${base}" y2="${base}" stroke="#30363d" stroke-dasharray="4 4"/>` +
    `<text x="${W-10}" y="${base-4}" fill="#8b949e" font-size="10" text-anchor="end">$${bankroll.toFixed(0)} start</text>` +
    `<path d="${path}" fill="none" stroke="${last>=bankroll?'#3fb950':'#f85149'}" stroke-width="1.5"/>`;
}

async function refresh() {
  let s;
  try { s = await (await fetch("/api/state")).json(); }
  catch(e) { document.getElementById("status").textContent = "server unreachable"; return; }
  const age = s.last_snapshot_ts ? (s.ts - s.last_snapshot_ts) : null;
  const live = age != null && age < 300;
  document.getElementById("status").innerHTML =
    `updated ${new Date().toLocaleTimeString()} · book data ` +
    (age==null ? '<span class="stale">none</span>'
     : live ? `<span class="ok">live (${Math.round(age)}s ago)</span>`
            : `<span class="stale">STALE (${Math.round(age/60)} min ago — is paper-run running?)</span>`) +
    ` · ${s.counts.markets} markets · ${s.counts.open_orders} resting orders · ${s.counts.snapshots} snapshots logged`;
  const total = s.realized + s.unrealized;
  document.getElementById("cards").innerHTML =
    card("Equity", "$"+fmt(s.equity), cls(total)) +
    card("Realized PnL", money(s.realized), cls(s.realized)) +
    card("Unrealized", money(s.unrealized), cls(s.unrealized)) +
    card("Fills", s.counts.fills) +
    card("Settled", s.settlements.length);
  drawChart(s.equity_history, s.bankroll);
  document.getElementById("positions").innerHTML = table(s.positions, [
    {h:"market", f:r=>r.question||r.token_id.slice(0,12), c:()=> "q"},
    {h:"qty", f:r=>fmt(r.qty,0)},
    {h:"avg", f:r=>fmt(r.avg_cost,3)},
    {h:"mark", f:r=>fmt(r.mark,3)},
    {h:"model", f:r=>fmt(r.model_prob,3)},
    {h:"cost", f:r=>"$"+fmt(r.cost)},
    {h:"uPnL", f:r=>money(r.upnl), c:r=>cls(r.upnl)},
  ]);
  document.getElementById("settlements").innerHTML = table(s.settlements, [
    {h:"when", f:r=>tdate(r.ts)},
    {h:"market", f:r=>r.question||"?", c:()=> "q"},
    {h:"outcome", f:r=>r.outcome ? "YES" : "NO"},
    {h:"qty", f:r=>fmt(r.qty,0)},
    {h:"PnL", f:r=>money(r.pnl), c:r=>cls(r.pnl)},
  ]);
  document.getElementById("fills").innerHTML = table(s.fills, [
    {h:"when", f:r=>tdate(r.ts)},
    {h:"market", f:r=>r.question||"?", c:()=> "q"},
    {h:"side", f:r=>r.side+" ("+r.kind+")"},
    {h:"px", f:r=>fmt(r.price,3)},
    {h:"size", f:r=>fmt(r.size,0)},
    {h:"model", f:r=>fmt(r.model_prob,3)},
    {h:"fee", f:r=>money(-r.fee).replace("+$","-$").replace("--","+")},
  ]);
}
refresh();
setInterval(refresh, 30000);
</script>
</body></html>"""


def make_handler(db_path: str, bankroll: float):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.startswith("/api/state"):
                body = json.dumps(compute_state(db_path, bankroll)).encode()
                ctype = "application/json"
            else:
                body = PAGE.encode()
                ctype = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # quiet
            pass

    return Handler


def run_dashboard(settings: Settings, port: int = 8787, db_path: str | None = None) -> None:
    db_path = db_path or settings.db_path
    bankroll = settings.paper.starting_bankroll_usd
    threading.Thread(
        target=_snapshot_loop, args=(db_path, bankroll), daemon=True
    ).start()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(db_path, bankroll))
    print(f"dashboard: http://127.0.0.1:{port}")
    server.serve_forever()
