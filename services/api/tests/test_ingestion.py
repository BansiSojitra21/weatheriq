from datetime import datetime, timezone

from app.db.models import WeatherObservation
from app.services.ingestion import upsert_observations
from app.services.open_meteo import parse_daily_archive

def test_parse_daily_archive_cleans_rows():
    payload = {
        "daily": {
            "time": ["2024-01-01", "2024-01-02"],
            "temperature_2m_mean": [10.5, 999],
            "temperature_2m_min": [4, 5],
            "temperature_2m_max": [14, 16],
            "precipitation_sum": [0, 3.2],
            "relative_humidity_2m_mean": [55, None],
            "wind_speed_10m_max": [12, 14],
            "pressure_msl_mean": [1012, 1010],
            "cloud_cover_mean": [20, 80],
            "weather_code": [1, 61],
        }
    }
    rows = parse_daily_archive(payload)
    assert len(rows) == 2
    assert rows[0]["temperature_c"] == 10.5
    assert rows[1]["temperature_c"] is None
    assert rows[1]["precipitation_mm"] == 3.2


def test_observation_upsert_is_idempotent(database):
    location_id = 1
    from app.db.models import Location

    database.add(Location(id=location_id, name="Test City", country="Test", latitude=1, longitude=2, timezone="UTC"))
    database.flush()
    retrieved = datetime(2024, 1, 3, tzinfo=timezone.utc)
    rows = [
        {
            "observed_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "temperature_c": 10,
            "precipitation_mm": 0,
        }
    ]
    assert upsert_observations(database, location_id, "daily", rows, retrieved) == 1
    rows[0]["temperature_c"] = 11
    assert upsert_observations(database, location_id, "daily", rows, retrieved) == 1
    database.commit()
    stored = database.query(WeatherObservation).all()
    assert len(stored) == 1
    assert stored[0].temperature_c == 11
