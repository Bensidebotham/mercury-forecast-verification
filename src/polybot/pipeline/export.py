"""Export the tidy evaluation frame to Parquet for the dashboard and portability."""
import json
import time
import pyarrow as pa
import pyarrow.parquet as pq

from polybot.analysis.verification import evaluation_frame, score_by_lead_time
from polybot.analysis.live import current_disagreements, tracking_summary

def export_evaluation(conn, out_path: str, lead_buckets=(72, 48, 24, 6)) -> int:
    frame = evaluation_frame(conn, lead_buckets)
    cols = ["market_uid", "city", "lead_hours", "model_prob", "market_prob", "outcome"]
    table = pa.table({c: [r[c] for r in frame] for c in cols} if frame
                     else {c: [] for c in cols})
    pq.write_table(table, out_path)
    return len(frame)

def export_json(conn, out_path: str, lead_buckets=(72, 48, 24, 6)) -> int:
    rows = evaluation_frame(conn, lead_buckets)
    doc = {
        "generated_ts": time.time(),
        "n_resolved": len(rows),
        "by_lead": score_by_lead_time(conn, lead_buckets),
        "rows": rows,
        "tracking": tracking_summary(conn),
        "live_disagreements": current_disagreements(conn, limit=25),
    }
    with open(out_path, "w") as f:
        json.dump(doc, f)
    return len(rows)
