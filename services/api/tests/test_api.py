from datetime import datetime, timezone

from app.db.models import Location, WeatherObservation


def test_health_and_seeded_locations(client):
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    body = health.json()
    assert body["database"] == "ok"
    assert "disclaimer" in body
    locations = client.get("/api/v1/locations")
    assert locations.status_code == 200
    names = {item["name"] for item in locations.json()["items"]}
    assert "Mumbai" in names


def test_history_returns_only_stored_observations(client, database):
    location = database.query(Location).filter_by(name="Mumbai").one()
    database.add(
        WeatherObservation(
            location_id=location.id,
            observed_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
            granularity="daily",
            temperature_c=31.2,
            precipitation_mm=0.4,
            humidity_pct=70,
            provider="open-meteo",
            retrieved_at=datetime(2024, 5, 2, tzinfo=timezone.utc),
        )
    )
    database.commit()
    response = client.get(
        "/api/v1/weather/history",
        params={"location_id": location.id, "start": "2024-05-01", "end": "2024-05-03"},
    )
    assert response.status_code == 200
    series = response.json()["series"]
    assert len(series) == 1
    assert series[0]["temperature"] == 31.2
    assert series[0]["temperature_min"] is None


def test_mutation_requires_api_key(client):
    rejected = client.post("/api/v1/risk/evaluate", json={})
    assert rejected.status_code == 401
    accepted = client.post("/api/v1/risk/evaluate", json={}, headers={"X-API-Key": "test-key"})
    assert accepted.status_code == 200
    assert accepted.json()["created"] == 0


def test_workflow_event_is_deduplicated(client):
    location = client.get("/api/v1/locations").json()["items"][0]
    payload = {
        "event_id": "evt-test-1",
        "location_id": location["id"],
        "timestamp": "2026-10-20T00:00:00Z",
        "source": "simulation",
        "variable": "temperature_c",
        "actual_value": 46,
        "threshold": 40,
        "severity": "warning",
        "rule_name": "Simulated heat",
    }
    headers = {"X-API-Key": "test-key"}
    first = client.post("/api/v1/workflows/weather-event", json=payload, headers=headers)
    second = client.post("/api/v1/workflows/weather-event", json=payload, headers=headers)
    assert first.status_code == 200
    assert first.json()["should_notify"] is True
    assert second.json()["already_processed"] is True
    assert second.json()["should_notify"] is False
    alerts = client.get("/api/v1/alerts")
    assert alerts.json()["total"] == 1
    assert alerts.json()["items"][0]["delivery"]["state"] == "not_delivered"
    delivery = client.post(
        "/api/v1/workflows/delivery",
        json={
            "alert_id": first.json()["alert_id"],
            "channel": "test",
            "destination": "test-mode",
            "status": "delivered",
        },
        headers=headers,
    )
    assert delivery.status_code == 200
    refreshed = client.get("/api/v1/alerts")
    assert refreshed.json()["items"][0]["delivery"]["state"] == "delivered"
    assert refreshed.json()["items"][0]["delivery"]["channel"] == "test"


def test_alert_rule_accepts_requested_severity_levels(client):
    location = client.get("/api/v1/locations").json()["items"][0]
    response = client.post(
        "/api/v1/alerts/rules",
        headers={"X-API-Key": "test-key"},
        json={
            "name": "Critical wind",
            "location_id": location["id"],
            "variable": "wind_speed_kmh",
            "operator": "gt",
            "threshold": 60,
            "severity": "critical",
        },
    )

    assert response.status_code == 200
    assert response.json()["severity"] == "critical"


def test_creating_matching_enabled_rule_records_alert_immediately(client, database):
    from datetime import datetime, timezone

    location = client.get("/api/v1/locations").json()["items"][0]
    database.add(
        WeatherObservation(
            location_id=location["id"],
            observed_at=datetime.now(timezone.utc),
            granularity="daily",
            temperature_c=27,
            temperature_max_c=27,
            provider="test",
            retrieved_at=datetime.now(timezone.utc),
        )
    )
    database.commit()
    response = client.post(
        "/api/v1/alerts/rules",
        headers={"X-API-Key": "test-key"},
        json={
            "name": "Warm today",
            "location_id": location["id"],
            "variable": "temperature_c",
            "operator": "gt",
            "threshold": 25,
            "severity": "high",
        },
    )

    assert response.status_code == 200
    assert response.json()["evaluation"]["created"] == 1
    alerts = client.get("/api/v1/alerts", params={"location_id": location["id"]}).json()["items"]
    assert any(alert["title"] == f"Warm today at {location['name']}" for alert in alerts)


def test_monitoring_and_correlation_handle_sqlite_timestamps(client, database):
    from datetime import datetime, timedelta, timezone

    from app.db.models import WeatherObservation

    start = datetime.now(timezone.utc) - timedelta(days=20)
    for offset in range(15):
        database.add(
            WeatherObservation(
                location_id=1,
                granularity="daily",
                observed_at=start + timedelta(days=offset),
                temperature_c=20 + offset * 0.2,
                precipitation_mm=float(offset % 3),
                humidity_pct=50 + offset,
                wind_speed_kmh=10,
                pressure_hpa=1010,
                cloud_cover_pct=20,
                retrieved_at=datetime.now(timezone.utc),
            )
        )
    database.commit()
    monitoring = client.get("/api/v1/monitoring")
    assert monitoring.status_code == 200
    assert monitoring.json()["missing_data"]["temperature_c"]["missing"] == 0
    end = (start + timedelta(days=14)).date().isoformat()
    correlation = client.get(f"/api/v1/analytics/correlation?location_id=1&start={start.date().isoformat()}&end={end}")
    assert correlation.status_code == 200
    assert correlation.json()["matrix"][0][0] == 1.0
