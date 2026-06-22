from polybot.pipeline.ingest import model_prob_for_market, validate_unified
from polybot.storage import verify_db


def test_validate_rejects_out_of_range_prob():
    assert validate_unified({"bucket_lo": 75.0, "bucket_hi": 76.0, "close_ts": 1.0}) is True
    assert validate_unified({"bucket_lo": None, "bucket_hi": None, "close_ts": 1.0}) is False


def test_model_prob_for_market_uses_ensemble(monkeypatch):
    import polybot.pipeline.ingest as ing
    monkeypatch.setattr(ing.ensemble, "get_ensemble_members",
                        lambda lat, lon, tz, date, unit: [75.5] * 40)
    monkeypatch.setattr(ing.obs, "get_running_max", lambda *a, **k: None)
    monkeypatch.setattr(ing.obs, "is_day_locked", lambda *a, **k: False)
    from polybot.config import City
    c = City(name="New York", station="KNYC", lat=40.7, lon=-74.0)
    p = model_prob_for_market(c, "2026-06-22",
                              {"bucket_lo": 75.0, "bucket_hi": 76.0}, sigma=1.5,
                              obs_buffer=1.5, locked_bias=0.75, locked_sigma=1.0)
    assert 0.0 <= p <= 1.0 and p > 0.2
