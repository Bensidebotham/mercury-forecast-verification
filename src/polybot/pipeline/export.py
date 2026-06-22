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
