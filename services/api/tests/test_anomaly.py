import math
from datetime import datetime, timedelta, timezone

from ml.anomaly import explain, is_flagged, modified_z, reference_bounds
from app.db.models import AppSetting
from app.services.anomaly_schedule import SCHEDULE_KEY, run_if_due, seconds_until_due


def test_robust_threshold_flags_only_the_unusual_point():
    history = [10] * 20
    bounds = reference_bounds(history, threshold=3.5)
    assert bounds is not None
    assert is_flagged(10, bounds, 3.5) is False
    assert is_flagged(100, bounds, 3.5) is True
    score = modified_z(100, bounds)
    text = explain("temperature_c", 100, bounds, score, 3.5)
    assert "Temperature" in text
    assert "not a hazard warning" in text
    assert math.isinf(score)


def test_short_history_is_not_scored():
    assert reference_bounds([1, 2, 3], threshold=3.5) is None


def test_detection_is_due_once_per_day():
    now = datetime(2026, 10, 22, 4, 30, tzinfo=timezone.utc)
    assert seconds_until_due(now, None) == 0
    assert seconds_until_due(now, now - timedelta(hours=23)) > 0
    assert seconds_until_due(now, now - timedelta(days=1)) == 0


def test_scheduled_detection_skips_a_second_run_the_same_day(database):
    moment = datetime(2026, 10, 22, 4, 30, tzinfo=timezone.utc)
    first = run_if_due(moment)
    second = run_if_due(moment + timedelta(hours=1))
    later = run_if_due(moment + timedelta(days=1))
    assert first is not None
    assert first["created_or_updated"] == 0
    assert second is None
    assert later is not None
    row = database.get(AppSetting, SCHEDULE_KEY)
    assert row is not None
    assert row.value["ran_at"] == (moment + timedelta(days=1)).isoformat()
