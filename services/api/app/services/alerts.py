from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import WeatherIQError
from app.db.models import Alert, AlertRule, CurrentCondition, ForecastRun, ForecastValue, Location, WeatherObservation
from app.services.catalog import as_utc, isoformat

OPERATORS = {
    "gt": lambda value, threshold: value > threshold,
    "gte": lambda value, threshold: value >= threshold,
    "lt": lambda value, threshold: value < threshold,
    "lte": lambda value, threshold: value <= threshold,
}


def _compare(operator: str, value: float, threshold: float) -> bool:
    try:
        function = OPERATORS[operator]
    except KeyError as exc:
        raise WeatherIQError(f"Unsupported operator '{operator}'.", code="invalid_operator") from exc
    return bool(function(value, threshold))


def _candidate_value(
    rule: AlertRule, observation: WeatherObservation | None, current: CurrentCondition | None
) -> tuple[float | None, str | None, datetime | None]:
    if rule.variable == "temperature_c":
        if rule.operator in {"gt", "gte"}:
            if observation and observation.temperature_max_c is not None:
                return observation.temperature_max_c, "observation", observation.observed_at
            if current and current.temperature_c is not None:
                return current.temperature_c, "observation", current.observed_at
        else:
            if observation and observation.temperature_min_c is not None:
                return observation.temperature_min_c, "observation", observation.observed_at
            if current and current.temperature_c is not None:
                return current.temperature_c, "observation", current.observed_at
        return None, None, None
    mapping = {
        "precipitation_mm": "precipitation_mm",
        "wind_speed_kmh": "wind_speed_kmh",
        "humidity_pct": "humidity_pct",
        "pressure_hpa": "pressure_hpa",
    }
    field = mapping.get(rule.variable)
    if field is None:
        return None, None, None
    if observation is not None and getattr(observation, field) is not None:
        return getattr(observation, field), "observation", observation.observed_at
    if current is not None and getattr(current, field) is not None:
        return getattr(current, field), "observation", current.observed_at
    return None, None, None


def _forecast_candidates(session: Session, location_id: int, rule: AlertRule) -> list[tuple[float, datetime]]:
    run = (
        session.query(ForecastRun)
        .filter_by(location_id=location_id, provider="open-meteo", model_name="forecast-daily")
        .one_or_none()
    )
    if run is None:
        return []
    values = session.query(ForecastValue).filter_by(run_id=run.id, granularity="daily").all()
    found = []
    for value in values:
        if rule.variable == "temperature_c":
            number = value.temperature_max_c if rule.operator in {"gt", "gte"} else value.temperature_min_c
        elif rule.variable == "precipitation_mm":
            number = value.precipitation_mm
        elif rule.variable == "wind_speed_kmh":
            number = value.wind_speed_kmh
        else:
            number = None
        if number is not None:
            found.append((float(number), as_utc(value.valid_at)))
    return found


def rule_out(rule: AlertRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "location_id": rule.location_id,
        "variable": rule.variable,
        "operator": rule.operator,
        "threshold": rule.threshold,
        "severity": rule.severity,
        "enabled": rule.enabled,
        "cooldown_minutes": rule.cooldown_minutes,
        "description": rule.description,
    }


def delivery_summary(alert: Alert) -> dict:
    deliveries = list(alert.deliveries)
    delivered = [item for item in deliveries if item.status == "delivered"]
    latest = max(deliveries, key=lambda item: item.attempted_at) if deliveries else None
    return {
        "state": "delivered" if delivered else ("failed" if latest and latest.status == "failed" else "not_delivered"),
        "channel": delivered[-1].channel if delivered else (latest.channel if latest else None),
        "destination": delivered[-1].destination if delivered else (latest.destination if latest else None),
        "attempted_at": isoformat(latest.attempted_at) if latest else None,
        "attempts": len(deliveries),
    }


def alert_out(alert: Alert, location_name: str | None = None) -> dict:
    return {
        "id": alert.id,
        "rule_id": alert.rule_id,
        "location_id": alert.location_id,
        "location_name": location_name,
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "title": alert.title,
        "message": alert.message,
        "variable": alert.variable,
        "threshold": alert.threshold,
        "actual_value": alert.actual_value,
        "event_time": isoformat(alert.event_time),
        "status": alert.status,
        "source": alert.source,
        "condition_kind": alert.condition_kind,
        "created_at": isoformat(alert.created_at),
        "acknowledged_at": isoformat(alert.acknowledged_at),
        "resolved_at": isoformat(alert.resolved_at),
        "delivery": delivery_summary(alert),
    }


def evaluate_rules(session: Session, location_id: int | None = None) -> dict:
    now = datetime.now(timezone.utc)
    rules = session.query(AlertRule).filter_by(enabled=True).all()
    locations = session.query(Location)
    if location_id is not None:
        locations = locations.filter_by(id=location_id)
    locations = locations.all()
    created = 0
    skipped = 0
    for rule in rules:
        scoped = [item for item in locations if rule.location_id in {None, item.id}]
        for location in scoped:
            observation = (
                session.query(WeatherObservation)
                .filter_by(location_id=location.id, granularity="daily")
                .order_by(WeatherObservation.observed_at.desc())
                .first()
            )
            current = (
                session.query(CurrentCondition)
                .filter_by(location_id=location.id)
                .order_by(CurrentCondition.observed_at.desc())
                .first()
            )
            checks: list[tuple[float, str, datetime]] = []
            value, kind, event_time = _candidate_value(rule, observation, current)
            if value is not None and kind and event_time:
                checks.append((value, kind, as_utc(event_time)))
            for forecast_value, valid_at in _forecast_candidates(session, location.id, rule):
                checks.append((forecast_value, "external_forecast", valid_at))
            for actual, condition_kind, event_time in checks:
                if not _compare(rule.operator, actual, rule.threshold):
                    continue
                bucket = event_time.strftime("%Y-%m-%d")
                dedupe_key = f"rule:{rule.id}:loc:{location.id}:var:{rule.variable}:src:{condition_kind}:t:{bucket}"
                if session.query(Alert).filter_by(dedupe_key=dedupe_key).one_or_none():
                    skipped += 1
                    continue
                cooldown_start = now - timedelta(minutes=rule.cooldown_minutes)
                recent = (
                    session.query(Alert)
                    .filter(
                        Alert.rule_id == rule.id,
                        Alert.location_id == location.id,
                        Alert.status != "resolved",
                        Alert.created_at >= cooldown_start,
                    )
                    .first()
                )
                if recent is not None:
                    skipped += 1
                    continue
                session.add(
                    Alert(
                        rule_id=rule.id,
                        location_id=location.id,
                        alert_type=rule.name,
                        severity=rule.severity,
                        title=f"{rule.name} at {location.name}",
                        message=(
                            f"{rule.variable} {rule.operator} {rule.threshold} was met by {condition_kind} "
                            f"value {actual:.2f} at {bucket}. This is a configured WeatherIQ rule, "
                            "not an official warning."
                        ),
                        variable=rule.variable,
                        threshold=rule.threshold,
                        actual_value=actual,
                        event_time=event_time,
                        status="open",
                        dedupe_key=dedupe_key,
                        source="rule",
                        condition_kind=condition_kind,
                    )
                )
                created += 1
                session.flush()
    return {"created": created, "skipped_duplicates": skipped}


def update_alert_status(session: Session, alert_id: int, status: str) -> Alert:
    if status not in {"open", "acknowledged", "resolved"}:
        raise WeatherIQError("Status must be open, acknowledged, or resolved.", code="invalid_status")
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise WeatherIQError("Alert not found.", status_code=404, code="not_found")
    now = datetime.now(timezone.utc)
    alert.status = status
    if status == "acknowledged":
        alert.acknowledged_at = now
    if status == "resolved":
        alert.resolved_at = now
    session.flush()
    return alert
