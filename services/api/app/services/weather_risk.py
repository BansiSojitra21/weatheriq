from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.db.models import ForecastRun, ForecastValue, Location
from app.services.catalog import as_utc, isoformat

RISK_PERIOD_DAYS = 3


def _bounded_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def daily_risk(value: ForecastValue) -> dict:
    factors: dict[str, dict[str, float]] = {}
    scores = []

    rain_scores = []
    if value.precipitation_probability is not None:
        rain_scores.append(_bounded_score(value.precipitation_probability))
    if value.precipitation_mm is not None:
        rain_scores.append(_bounded_score(value.precipitation_mm / 50 * 100))
    if rain_scores:
        rain_score = max(rain_scores)
        factors["rain"] = {
            "score": rain_score,
            "precipitation_probability": value.precipitation_probability,
            "precipitation_mm": value.precipitation_mm,
        }
        scores.append(("rain", rain_score))

    if value.wind_speed_kmh is not None:
        wind_score = _bounded_score(value.wind_speed_kmh / 60 * 100)
        factors["wind"] = {"score": wind_score, "wind_speed_kmh": value.wind_speed_kmh}
        scores.append(("wind", wind_score))

    if value.temperature_max_c is not None:
        heat_score = _bounded_score((value.temperature_max_c - 30) / 15 * 100)
        factors["heat"] = {"score": heat_score, "temperature_max_c": value.temperature_max_c}
        scores.append(("heat", heat_score))

    if value.temperature_min_c is not None:
        cold_score = _bounded_score((5 - value.temperature_min_c) / 15 * 100)
        factors["cold"] = {"score": cold_score, "temperature_min_c": value.temperature_min_c}
        scores.append(("cold", cold_score))

    highest = max(scores, key=lambda item: item[1]) if scores else None
    return {
        "score": None if highest is None else highest[1],
        "primary_driver": None if highest is None else highest[0],
        "factors": factors,
    }


def risk_level(score: float | None) -> str:
    if score is None:
        return "unavailable"
    if score < 25:
        return "low"
    if score < 50:
        return "moderate"
    if score < 75:
        return "high"
    return "critical"


def _location_date(moment: datetime, location: Location) -> date:
    try:
        zone = ZoneInfo(location.timezone or "UTC")
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    return as_utc(moment).astimezone(zone).date()


def risk_overview(session: Session, now: datetime | None = None) -> dict:
    current_time = as_utc(now or datetime.now(timezone.utc))
    locations = session.query(Location).order_by(Location.name).all()
    items = []

    for location in locations:
        run = (
            session.query(ForecastRun)
            .filter_by(location_id=location.id, provider="open-meteo", model_name="forecast-daily")
            .order_by(ForecastRun.retrieved_at.desc())
            .first()
        )
        forecasts = []
        if run is not None:
            start_day = _location_date(current_time, location)
            end_day = start_day + timedelta(days=RISK_PERIOD_DAYS - 1)
            values = (
                session.query(ForecastValue)
                .filter_by(run_id=run.id, granularity="daily")
                .order_by(ForecastValue.valid_at.asc())
                .all()
            )
            for value in values:
                forecast_day = _location_date(value.valid_at, location)
                if start_day <= forecast_day <= end_day:
                    result = daily_risk(value)
                    if result["score"] is not None:
                        forecasts.append(
                            {
                                "valid_at": isoformat(value.valid_at),
                                **result,
                            }
                        )

        highest = max(forecasts, key=lambda item: item["score"], default=None)
        score = None if highest is None else highest["score"]
        items.append(
            {
                "location_id": location.id,
                "location_name": location.name,
                "latitude": location.latitude,
                "longitude": location.longitude,
                "score": score,
                "level": risk_level(score),
                "primary_driver": None if highest is None else highest["primary_driver"],
                "valid_at": None if highest is None else highest["valid_at"],
                "factors": {} if highest is None else highest["factors"],
                "forecast_retrieved_at": None if run is None else isoformat(run.retrieved_at),
                "days_with_data": len(forecasts),
            }
        )

    items.sort(key=lambda item: (-1 if item["score"] is None else item["score"]), reverse=True)
    return {
        "items": items,
        "as_of": isoformat(current_time),
        "period_days": RISK_PERIOD_DAYS,
        "method": {
            "name": "Transparent threshold index",
            "description": (
                "Uses the highest available normalized factor score over the next three local forecast days. "
                "It is a planning aid, not a calibrated probability, official warning, or safety assessment."
            ),
            "thresholds": {
                "rain_probability_pct": 100,
                "rainfall_mm": 50,
                "wind_speed_kmh": 60,
                "heat_max_c": {"baseline": 30, "maximum": 45},
                "cold_min_c": {"baseline": 5, "maximum": -10},
            },
        },
    }
