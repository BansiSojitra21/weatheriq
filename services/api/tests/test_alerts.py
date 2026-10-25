from datetime import datetime, timezone

from app.db.models import AlertRule, Location, WeatherObservation
from app.services.alerts import evaluate_rules


def test_alert_evaluation_suppresses_duplicates(database):
    location = Location(name="Alert City", country="Test", latitude=10, longitude=10, timezone="UTC")
    database.add(location)
    database.flush()
    database.add(
        WeatherObservation(
            location_id=location.id,
            observed_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            granularity="daily",
            temperature_max_c=45,
            temperature_c=42,
            precipitation_mm=0,
            provider="test",
            retrieved_at=datetime(2024, 6, 2, tzinfo=timezone.utc),
        )
    )
    database.add(
        AlertRule(
            name="Heat",
            location_id=location.id,
            variable="temperature_c",
            operator="gt",
            threshold=40,
            severity="warning",
            enabled=True,
            cooldown_minutes=720,
        )
    )
    database.commit()
    first = evaluate_rules(database, location.id)
    second = evaluate_rules(database, location.id)
    assert first["created"] == 1
    assert second["created"] == 0
    assert second["skipped_duplicates"] >= 1
