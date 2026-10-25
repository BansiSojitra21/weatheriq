from datetime import datetime, timedelta, timezone

from app.db.models import ForecastRun, ForecastValue, Location
from app.services.weather_risk import daily_risk, risk_level


def test_daily_risk_uses_highest_available_factor_and_clamps_scores():
    value = ForecastValue(
        precipitation_probability=60,
        precipitation_mm=10,
        wind_speed_kmh=90,
        temperature_max_c=36,
        temperature_min_c=18,
    )

    result = daily_risk(value)

    assert result["score"] == 100
    assert result["primary_driver"] == "wind"
    assert result["factors"]["rain"]["score"] == 60
    assert result["factors"]["heat"]["score"] == 40


def test_risk_levels_distinguish_missing_data():
    assert risk_level(None) == "unavailable"
    assert risk_level(24.9) == "low"
    assert risk_level(25) == "moderate"
    assert risk_level(50) == "high"
    assert risk_level(75) == "critical"


def test_risk_overview_reports_missing_forecasts_without_zero_scores(client, database):
    from app.services.weather_risk import risk_overview

    result = risk_overview(database)

    assert result["period_days"] == 3
    assert len(result["items"]) >= 1
    assert all(item["score"] is None for item in result["items"])


def test_risk_overview_uses_highest_risk_in_next_local_forecast_days(client, database):
    location = database.query(Location).filter_by(name="Surat").one()
    retrieved_at = datetime.now(timezone.utc)
    run = ForecastRun(
        location_id=location.id,
        provider="open-meteo",
        model_name="forecast-daily",
        issued_at=retrieved_at,
        retrieved_at=retrieved_at,
    )
    database.add(run)
    database.flush()
    database.add_all(
        [
            ForecastValue(
                run_id=run.id,
                valid_at=retrieved_at + timedelta(days=1),
                granularity="daily",
                precipitation_probability=15,
                precipitation_mm=0,
                wind_speed_kmh=10,
                temperature_max_c=32,
                temperature_min_c=20,
            ),
            ForecastValue(
                run_id=run.id,
                valid_at=retrieved_at + timedelta(days=2),
                granularity="daily",
                precipitation_probability=30,
                precipitation_mm=20,
                wind_speed_kmh=12,
                temperature_max_c=34,
                temperature_min_c=20,
            ),
        ]
    )
    database.commit()

    result = client.get("/api/v1/risk/overview")

    assert result.status_code == 200
    surat = next(item for item in result.json()["items"] if item["location_name"] == "Surat")
    assert surat["score"] == 40, result.json()
    assert surat["level"] == "moderate"
    assert surat["primary_driver"] == "rain"
    assert surat["days_with_data"] == 2
