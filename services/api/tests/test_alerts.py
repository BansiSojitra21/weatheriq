from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from app.db.models import AlertRule, Location, WeatherObservation
from app.services.alerts import evaluate_rules


def test_alert_evaluation_suppresses_duplicates(database):
    location = Location(name="Alert City", country="Test", latitude=10, longitude=10, timezone="UTC")
    database.add(location)
    database.flush()
    database.add(
        WeatherObservation(
            location_id=location.id,
            observed_at=datetime.now(timezone.utc),
            granularity="daily",
            temperature_max_c=45,
            temperature_c=42,
            precipitation_mm=0,
            provider="test",
            retrieved_at=datetime.now(timezone.utc),
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


def test_scheduled_alert_check_evaluates_enabled_rules(database, monkeypatch):
    from app.services import alert_schedule

    location = Location(name="Scheduled City", country="Test", latitude=10, longitude=10, timezone="UTC")
    database.add(location)
    database.flush()
    database.add_all(
        [
            WeatherObservation(
                location_id=location.id,
                observed_at=datetime.now(timezone.utc),
                granularity="daily",
                temperature_max_c=32,
                temperature_c=29,
                provider="test",
                retrieved_at=datetime.now(timezone.utc),
            ),
            AlertRule(
                name="Automatic heat",
                location_id=location.id,
                variable="temperature_c",
                operator="gt",
                threshold=30,
                severity="high",
                enabled=True,
            ),
        ]
    )
    database.commit()
    factory = sessionmaker(bind=database.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(alert_schedule.db_session, "SessionLocal", factory)
    monkeypatch.setattr(alert_schedule, "ensure_fresh_current", lambda _session, _location: None)

    result = alert_schedule.run_alert_check()

    assert result["created"] == 1
