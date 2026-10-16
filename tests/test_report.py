import json

from weather_vs_market.pipeline import report as R


def _doc(diff_ci=(0.10, 0.20)):
    s = {"lead": "D-1 12:00", "n_events": 1800, "model_brier": 0.80, "market_brier": 0.65,
         "brier_diff": 0.15, "brier_diff_ci": list(diff_ci), "model_rps": 0.05, "market_rps": 0.04,
         "rps_diff": 0.01, "rps_diff_ci": [0.005, 0.015], "model_logscore": 1.9,
         "market_logscore": 1.5, "logscore_diff": 0.4, "logscore_diff_ci": [0.3, 0.5]}
    return {"window": ["2025-07-01", "2026-09-30"], "train_window": ["2024-01-01", "2025-06-30"],
            "git_sha": "abc1234def",
            "data_quality": {"kalshi_cli_agreement": {"n": 10, "agree": 9, "rate": 0.9}},
            "venues": {"kalshi": {"summary": [s], "stats": {"events_in_window": 1820, "scored": 1800},
                                  "date_span": ["2025-07-01", "2026-09-30"], "by_city": [],
                                  "calibration": {}},
                       "polymarket": {"summary": [], "stats": {}, "date_span": None, "by_city": [],
                                      "calibration": {}}}}


def test_headline_states_direction_only_when_interval_excludes_zero():
    assert "market was more accurate" in R.headline(_doc())
    assert "no clear difference" in R.headline(_doc(diff_ci=(-0.01, 0.02)))


def test_results_table_has_every_scored_venue_and_lead():
    md = R.results_table(_doc())
    assert "| Kalshi | D-1 12:00 | 1,800 | 0.800 | 0.650 | +0.150 [+0.100, +0.200] |" in md
    assert "Polymarket" not in md


def test_replace_between_markers(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("intro\n<!-- results:start -->\nold\n<!-- results:end -->\nrest\n")
    R.replace_block(readme, "results", "new")
    assert readme.read_text() == "intro\n<!-- results:start -->\nnew\n<!-- results:end -->\nrest\n"


def test_write_reports_from_results_file(tmp_path, monkeypatch):
    results = tmp_path / "backtest_test.json"
    results.write_text(json.dumps(_doc()))
    readme = tmp_path / "README.md"
    readme.write_text("<!-- headline:start -->\n<!-- headline:end -->\n"
                      "<!-- results:start -->\n<!-- results:end -->\n")
    out = tmp_path / "RESULTS.md"
    R.write_reports(results, readme, out)
    assert "1,800" in readme.read_text() and "abc1234" in out.read_text()
