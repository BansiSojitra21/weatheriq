from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.db.models import CurrentCondition, ForecastRun, ForecastValue, Location, WeatherObservation
from app.services.ingestion import catch_up_daily_history
from app.services.seed import seed_defaults


def test_stale_snapshot_is_refreshed_before_current_weather_is_returned(client, database, monkeypatch):
    location = database.query(Location).filter_by(name="Mumbai").one()
    observed = datetime(2026, 10, 21, 12, 50, tzinfo=timezone.utc)
    database.add(
        CurrentCondition(
            location_id=location.id,
            observed_at=observed,
            temperature_c=31.8,
            weather_code=0,
            provider="open-meteo",
            retrieved_at=observed,
        )
    )
    database.commit()

    def fake_ingest(session, loc, **kwargs):
        assert loc.id == location.id
        assert kwargs["kinds"] == {"current", "forecast"}
        row = session.query(CurrentCondition).filter_by(location_id=loc.id).one()
        row.temperature_c = 33.4
        row.observed_at = datetime.now(timezone.utc).replace(microsecond=0)
        row.retrieved_at = datetime.now(timezone.utc)
        session.flush()
        return {"records": 1}

    monkeypatch.setattr("app.services.ingestion.ingest_location", fake_ingest)
    response = client.get("/api/v1/weather/current", params={"location_id": location.id})
    assert response.status_code == 200
    body = response.json()
    assert body["observation"]["temperature"] == 33.4
    assert body["freshness"]["stale"] is False
    updated = datetime.fromisoformat(body["freshness"]["retrieved_at"].replace("Z", "+00:00"))
    assert datetime.now(timezone.utc) - updated < timedelta(minutes=5)


def test_current_weather_uses_the_local_day_instead_of_the_previous_forecast_day(client, database, monkeypatch):
    def fail_ingest(*_args, **_kwargs):
        raise AssertionError("A fresh snapshot should stay in the database.")

    monkeypatch.setattr("app.services.ingestion.ingest_location", fail_ingest)
    location = database.query(Location).filter_by(name="Mumbai").one()
    zone = ZoneInfo("Asia/Kolkata")
    now = datetime.now(timezone.utc)
    local_today = now.astimezone(zone).date()
    yesterday = local_today - timedelta(days=1)

    def local_midnight(day):
        return datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(timezone.utc)

    database.add(
        CurrentCondition(
            location_id=location.id,
            observed_at=now.replace(microsecond=0),
            temperature_c=32.0,
            provider="open-meteo",
            retrieved_at=now,
        )
    )
    run = ForecastRun(
        location_id=location.id,
        provider="open-meteo",
        model_name="forecast-daily",
        issued_at=now,
        retrieved_at=now,
        issuance_basis="retrieval_time",
    )
    database.add(run)
    database.flush()
    database.add_all(
        [
            ForecastValue(
                run_id=run.id,
                valid_at=local_midnight(yesterday),
                granularity="daily",
                temperature_min_c=24.0,
                temperature_max_c=40.0,
            ),
            ForecastValue(
                run_id=run.id,
                valid_at=local_midnight(local_today),
                granularity="daily",
                temperature_min_c=25.0,
                temperature_max_c=29.0,
            ),
        ]
    )
    database.commit()

    response = client.get("/api/v1/weather/current", params={"location_id": location.id})
    assert response.status_code == 200
    body = response.json()
    assert body["today_forecast"]["temperature_max"] == 29.0
    assert body["today_forecast"]["temperature_min"] == 25.0
    assert [item["temperature_max"] for item in body["daily"]] == [29.0]
    expected = local_midnight(local_today).isoformat().replace("+00:00", "Z")
    assert body["today_forecast"]["valid_at"] == expected


def test_daily_history_catches_up_through_yesterday(database, monkeypatch):
    seed_defaults(database)
    location = database.query(Location).filter_by(name="Mumbai").one()
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    latest_day = yesterday - timedelta(days=1)
    database.add(
        WeatherObservation(
            location_id=location.id,
            observed_at=datetime(latest_day.year, latest_day.month, latest_day.day, tzinfo=timezone.utc),
            granularity="daily",
            temperature_c=31.0,
            provider="open-meteo",
            retrieved_at=datetime(latest_day.year, latest_day.month, latest_day.day, tzinfo=timezone.utc),
        )
    )
    database.commit()

    def fake_fetch(url, **_kwargs):
        assert f"start_date={yesterday.isoformat()}" in url
        assert f"end_date={yesterday.isoformat()}" in url
        return {
            "daily": {
                "time": [yesterday.isoformat()],
                "temperature_2m_mean": [33.0],
                "temperature_2m_max": [36.0],
                "temperature_2m_min": [25.0],
            }
        }

    monkeypatch.setattr("app.services.ingestion.fetch_json", fake_fetch)

    def already_stored(*_args, **_kwargs):
        from sqlalchemy.exc import IntegrityError

        raise IntegrityError("INSERT", {}, Exception("unique"))

    monkeypatch.setattr("app.services.ingestion.upsert_observations", already_stored)
    assert catch_up_daily_history(database, location) == 0
    assert database.query(Location).filter_by(id=location.id).one().name == "Mumbai"
    monkeypatch.undo()
    monkeypatch.setattr("app.services.ingestion.fetch_json", fake_fetch)
    assert catch_up_daily_history(database, location) == 1
    stored = (
        database.query(WeatherObservation)
        .filter_by(location_id=location.id, granularity="daily")
        .order_by(WeatherObservation.observed_at.desc())
        .first()
    )
    assert stored is not None
    assert stored.observed_at.date().isoformat() == yesterday.isoformat()
    assert stored.temperature_c == 33.0
    assert catch_up_daily_history(database, location) == 0
