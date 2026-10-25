from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.db.models import (
    Alert,
    AnomalyEvent,
    CurrentCondition,
    ForecastRun,
    ForecastValue,
    Location,
)
from app.services.alerts import alert_out
from app.services.anomaly_service import anomaly_out
from app.services.catalog import (
    ATTRIBUTION,
    DISCLAIMER,
    SOURCE_NOTE,
    UNIT_LABELS,
    as_utc,
    compass,
    condition_label,
    convert_precipitation,
    convert_pressure,
    convert_temperature,
    convert_wind,
    isoformat,
)


def location_out(location: Location) -> dict:
    return {
        "id": location.id,
        "name": location.name,
        "country": location.country,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "timezone": location.timezone,
        "elevation_m": location.elevation_m,
        "is_default": location.is_default,
    }


def _field(value, available: dict, key: str):
    available[key] = value is not None
    return value


def _location_zone(location: Location):
    try:
        return ZoneInfo(location.timezone or "UTC")
    except ZoneInfoNotFoundError:
        return timezone.utc


def _local_date(moment: datetime, location: Location):
    return as_utc(moment).astimezone(_location_zone(location)).date()


def current_payload(session: Session, location: Location, units: str) -> dict:
    current = (
        session.query(CurrentCondition)
        .filter_by(location_id=location.id)
        .order_by(CurrentCondition.observed_at.desc())
        .first()
    )
    daily_run = (
        session.query(ForecastRun)
        .filter_by(location_id=location.id, provider="open-meteo", model_name="forecast-daily")
        .one_or_none()
    )
    hourly_run = (
        session.query(ForecastRun)
        .filter_by(location_id=location.id, provider="open-meteo", model_name="forecast-hourly")
        .one_or_none()
    )
    available: dict[str, bool] = {}
    observation = None
    retrieved_at = None
    if current is not None:
        retrieved_at = as_utc(current.retrieved_at)
        observation = {
            "kind": "current_condition",
            "provider": current.provider,
            "source_note": SOURCE_NOTE,
            "observed_at": isoformat(current.observed_at),
            "retrieved_at": isoformat(current.retrieved_at),
            "temperature": _field(convert_temperature(current.temperature_c, units), available, "temperature"),
            "apparent_temperature": _field(
                convert_temperature(current.apparent_temperature_c, units), available, "apparent_temperature"
            ),
            "humidity": _field(
                None if current.humidity_pct is None else round(current.humidity_pct, 2), available, "humidity"
            ),
            "precipitation": _field(convert_precipitation(current.precipitation_mm, units), available, "precipitation"),
            "wind_speed": _field(convert_wind(current.wind_speed_kmh, units), available, "wind_speed"),
            "wind_direction_deg": _field(current.wind_direction_deg, available, "wind_direction"),
            "wind_direction": compass(current.wind_direction_deg),
            "pressure": _field(convert_pressure(current.pressure_hpa, units), available, "pressure"),
            "cloud_cover": _field(
                None if current.cloud_cover_pct is None else round(current.cloud_cover_pct, 2), available, "cloud_cover"
            ),
            "weather_code": current.weather_code,
            "condition": condition_label(current.weather_code),
            "available": available,
        }
    today = None
    daily = []
    today_date = datetime.now(timezone.utc).astimezone(_location_zone(location)).date()
    if daily_run is not None:
        values = (
            session.query(ForecastValue)
            .filter_by(run_id=daily_run.id, granularity="daily")
            .order_by(ForecastValue.valid_at.asc())
            .all()
        )
        for value in values:
            valid_day = _local_date(value.valid_at, location)
            if valid_day < today_date:
                continue
            item = {
                "kind": "external_forecast",
                "valid_at": isoformat(value.valid_at),
                "temperature_min": convert_temperature(value.temperature_min_c, units),
                "temperature_max": convert_temperature(value.temperature_max_c, units),
                "precipitation": convert_precipitation(value.precipitation_mm, units),
                "precipitation_probability": value.precipitation_probability,
                "wind_speed": convert_wind(value.wind_speed_kmh, units),
                "weather_code": value.weather_code,
                "condition": condition_label(value.weather_code),
                "sunrise": isoformat(value.sunrise_at),
                "sunset": isoformat(value.sunset_at),
                "provider": "open-meteo",
                "retrieved_at": isoformat(daily_run.retrieved_at),
            }
            daily.append(item)
            if today is None and valid_day == today_date:
                today = item
    hourly = []
    if hourly_run is not None:
        now = datetime.now(timezone.utc) - timedelta(hours=1)
        until = datetime.now(timezone.utc) + timedelta(hours=48)
        values = (
            session.query(ForecastValue)
            .filter(
                ForecastValue.run_id == hourly_run.id,
                ForecastValue.granularity == "hourly",
                ForecastValue.valid_at >= now,
                ForecastValue.valid_at <= until,
            )
            .order_by(ForecastValue.valid_at.asc())
            .all()
        )
        for value in values:
            hourly.append(
                {
                    "kind": "external_forecast",
                    "valid_at": isoformat(value.valid_at),
                    "temperature": convert_temperature(value.temperature_c, units),
                    "precipitation": convert_precipitation(value.precipitation_mm, units),
                    "precipitation_probability": value.precipitation_probability,
                    "wind_speed": convert_wind(value.wind_speed_kmh, units),
                    "provider": "open-meteo",
                }
            )
    names = {location.id: location.name}
    alerts = session.query(Alert).filter_by(location_id=location.id).order_by(Alert.event_time.desc()).limit(5).all()
    anomalies = (
        session.query(AnomalyEvent)
        .filter_by(location_id=location.id)
        .order_by(AnomalyEvent.observed_at.desc())
        .limit(5)
        .all()
    )
    age = None
    stale = None
    if retrieved_at is not None:
        age = int((datetime.now(timezone.utc) - retrieved_at).total_seconds())
        stale = age > 3 * 3600
    return {
        "location": location_out(location),
        "units": units,
        "unit_labels": UNIT_LABELS[units],
        "observation": observation,
        "today_forecast": today,
        "hourly": hourly,
        "daily": daily,
        "recent_alerts": [alert_out(item, names.get(item.location_id)) for item in alerts],
        "recent_anomalies": [anomaly_out(item, names.get(item.location_id)) for item in anomalies],
        "freshness": {"retrieved_at": isoformat(retrieved_at), "age_seconds": age, "stale": stale},
        "attribution": ATTRIBUTION,
        "disclaimer": DISCLAIMER,
    }
