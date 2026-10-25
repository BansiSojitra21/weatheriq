from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import session as db_session
from app.db.models import AlertRule, AppSetting, Location

DEFAULT_LOCATIONS = [
    {
        "name": "Ahmedabad",
        "country": "India",
        "latitude": 23.0225,
        "longitude": 72.5714,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Bengaluru",
        "country": "India",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Bhopal",
        "country": "India",
        "latitude": 23.2599,
        "longitude": 77.4126,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Chandigarh",
        "country": "India",
        "latitude": 30.7333,
        "longitude": 76.7794,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Chennai",
        "country": "India",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Delhi",
        "country": "India",
        "latitude": 28.6139,
        "longitude": 77.209,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Guwahati",
        "country": "India",
        "latitude": 26.1445,
        "longitude": 91.7362,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Hyderabad",
        "country": "India",
        "latitude": 17.385,
        "longitude": 78.4867,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Indore",
        "country": "India",
        "latitude": 22.7196,
        "longitude": 75.8577,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Jaipur",
        "country": "India",
        "latitude": 26.9124,
        "longitude": 75.7873,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Kochi",
        "country": "India",
        "latitude": 9.9312,
        "longitude": 76.2673,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Kolkata",
        "country": "India",
        "latitude": 22.5726,
        "longitude": 88.3639,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Lucknow",
        "country": "India",
        "latitude": 26.8467,
        "longitude": 80.9462,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Mumbai",
        "country": "India",
        "latitude": 19.076,
        "longitude": 72.8777,
        "timezone": "Asia/Kolkata",
        "is_default": True,
    },
    {
        "name": "Nagpur",
        "country": "India",
        "latitude": 21.1458,
        "longitude": 79.0882,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Patna",
        "country": "India",
        "latitude": 25.5941,
        "longitude": 85.1376,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Pune",
        "country": "India",
        "latitude": 18.5204,
        "longitude": 73.8567,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Surat",
        "country": "India",
        "latitude": 21.1702,
        "longitude": 72.8311,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Thiruvananthapuram",
        "country": "India",
        "latitude": 8.5241,
        "longitude": 76.9366,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
    {
        "name": "Visakhapatnam",
        "country": "India",
        "latitude": 17.6868,
        "longitude": 83.2185,
        "timezone": "Asia/Kolkata",
        "is_default": False,
    },
]

DEFAULT_RULES = [
    {
        "name": "High temperature",
        "variable": "temperature_c",
        "operator": "gt",
        "threshold": 40,
        "severity": "warning",
        "description": "Daily high or current temperature above 40 °C.",
    },
    {
        "name": "Freezing temperature",
        "variable": "temperature_c",
        "operator": "lt",
        "threshold": 0,
        "severity": "watch",
        "description": "Daily low or current temperature below 0 °C.",
    },
    {
        "name": "Heavy daily precipitation",
        "variable": "precipitation_mm",
        "operator": "gt",
        "threshold": 50,
        "severity": "warning",
        "description": "Daily precipitation total above 50 mm.",
    },
    {
        "name": "Strong wind",
        "variable": "wind_speed_kmh",
        "operator": "gt",
        "threshold": 60,
        "severity": "watch",
        "description": "Wind speed above 60 km/h.",
    },
]


def default_settings(default_location_id: int | None) -> dict:
    return {
        "default_location_id": default_location_id,
        "units": "metric",
        "timezone_mode": "location",
        "variables": [
            "temperature",
            "precipitation",
            "humidity",
            "wind_speed",
            "pressure",
            "cloud_cover",
        ],
        "anomaly_z_threshold": 3.5,
        "anomaly_window_days": 30,
        "history_days": 730,
        "hourly_days": 21,
        "notification_test_mode": True,
        "notification_email": "",
        "slack_configured": False,
        "refresh_hours": 1,
    }


def seed_defaults(session: Session | None = None) -> None:
    owns_session = session is None
    if owns_session:
        db_session.init_database()
        assert db_session.SessionLocal is not None
        session = db_session.SessionLocal()
    assert session is not None
    try:
        for item in DEFAULT_LOCATIONS:
            exists = (
                session.query(Location)
                .filter_by(name=item["name"], latitude=item["latitude"], longitude=item["longitude"])
                .one_or_none()
            )
            if exists is None:
                session.add(Location(**item))
        session.flush()
        for item in DEFAULT_RULES:
            exists = session.query(AlertRule).filter_by(name=item["name"]).one_or_none()
            if exists is None:
                session.add(AlertRule(**item, enabled=True, cooldown_minutes=720))
        default_location = session.query(Location).filter_by(is_default=True).one_or_none()
        if session.get(AppSetting, "app") is None:
            session.add(
                AppSetting(
                    key="app",
                    value=default_settings(default_location.id if default_location else None),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        session.commit()
    finally:
        if owns_session:
            session.close()
