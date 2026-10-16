from weather_vs_market.pipeline.settle import kalshi_outcomes, outcome_from_result


def test_outcome_from_result():
    assert outcome_from_result("yes") == 1
    assert outcome_from_result("no") == 0
    assert outcome_from_result(None) is None
    assert outcome_from_result("") is None


def test_kalshi_outcomes_only_for_known_markets_with_results():
    raw = [{"ticker": "A", "result": "yes"}, {"ticker": "B", "result": "no"},
           {"ticker": "C", "result": "yes"}, {"ticker": "D", "result": ""}]
    assert kalshi_outcomes(raw, {"kalshi:A", "kalshi:B", "kalshi:D"}) == [
        ("kalshi:A", 1), ("kalshi:B", 0)]
