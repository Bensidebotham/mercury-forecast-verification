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
