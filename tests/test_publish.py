import pyarrow.parquet as pq

from conftest import market
from weather_vs_market.config import load_settings
from weather_vs_market.pipeline import publish as P
from weather_vs_market.storage import store as S


def test_publish_stores_doc_for_dashboard(engine, tmp_path):
    S.upsert_markets(engine, [market()])
    out = tmp_path / "e.json"
    doc = P.publish(load_settings(), engine, out_file=str(out))
    assert doc["schema_version"] == P.SCHEMA_VERSION
    assert S.latest_published(engine)["generated_ts"] == doc["generated_ts"]
    assert set(doc) >= {"backtest", "live", "tracking", "live_disagreements"}
    assert doc["tracking"]["n_markets"] == 1
    assert out.exists()


def test_dump_tables_writes_parquet(engine, tmp_path):
    S.upsert_markets(engine, [market()])
    counts = P.dump_tables(engine, str(tmp_path / "dump"))
    assert counts["vmarket"] == 1
    assert pq.read_table(str(tmp_path / "dump" / "vmarket.parquet")).num_rows == 1
