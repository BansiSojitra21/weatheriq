from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import WeatherIQError
from app.db.models import Alert, Location, NotificationDelivery, WeatherReport, WorkflowEvent
from app.services.alerts import alert_out
from app.services.catalog import as_utc, isoformat


def accept_weather_event(session: Session, payload: dict) -> dict:
    required = ["event_id", "location_id", "timestamp", "source"]
    missing = [field for field in required if payload.get(field) in {None, ""}]
    if missing:
        raise WeatherIQError(f"Missing workflow fields: {missing}", code="invalid_event")
    event_id = str(payload["event_id"])
    existing = session.query(WorkflowEvent).filter_by(event_id=event_id).one_or_none()
    if existing is not None:
        return {
            "already_processed": True,
            "should_notify": False,
            "event_id": event_id,
            "alert_id": existing.alert_id,
        }
    location = session.get(Location, int(payload["location_id"]))
    if location is None:
        raise WeatherIQError("Location not found.", status_code=404, code="not_found")
    try:
        timestamp = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise WeatherIQError("timestamp must be ISO-8601.", code="invalid_event") from exc
    timestamp = as_utc(timestamp)
    severity = str(payload.get("severity") or "info")
    if severity not in {"info", "watch", "warning"}:
        raise WeatherIQError("severity must be info, watch, or warning.", code="invalid_event")
    actual = payload.get("actual_value")
    threshold = payload.get("threshold")
    variable = str(payload.get("variable") or "unspecified")
    alert = Alert(
        location_id=location.id,
        alert_type=str(payload.get("rule_name") or "Workflow event"),
        severity=severity,
        title=f"{payload.get('rule_name') or 'Weather event'} at {location.name}",
        message=str(payload.get("message") or f"Workflow event {event_id} from {payload['source']}."),
        variable=variable,
        threshold=None if threshold is None else float(threshold),
        actual_value=None if actual is None else float(actual),
        event_time=timestamp,
        status="open",
        dedupe_key=f"workflow:{event_id}",
        source="workflow",
        condition_kind=str(payload.get("condition_kind") or "workflow"),
    )
    session.add(alert)
    session.flush()
    event = WorkflowEvent(
        event_id=event_id,
        location_id=location.id,
        source=str(payload["source"]),
        payload=payload,
        status="processed",
        alert_id=alert.id,
        processed_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.flush()
    return {
        "already_processed": False,
        "should_notify": True,
        "event_id": event_id,
        "alert_id": alert.id,
        "alert": alert_out(alert, location.name),
    }


def record_delivery(session: Session, payload: dict) -> dict:
    status = str(payload.get("status") or "")
    if status not in {"pending", "delivered", "failed"}:
        raise WeatherIQError("status must be pending, delivered, or failed.", code="invalid_delivery")
    channel = str(payload.get("channel") or "test")
    destination = str(payload.get("destination") or "")
    alert_id = payload.get("alert_id")
    report_id = payload.get("report_id")
    if alert_id is None and report_id is None:
        raise WeatherIQError("alert_id or report_id is required.", code="invalid_delivery")
    if alert_id is not None:
        alert = session.get(Alert, int(alert_id))
        if alert is None:
            raise WeatherIQError("Alert not found.", status_code=404, code="not_found")
        delivered = session.query(NotificationDelivery).filter_by(alert_id=alert.id, status="delivered").first()
        if delivered is not None and status == "delivered":
            return {"id": delivered.id, "status": delivered.status, "duplicate": True}
    if report_id is not None and session.get(WeatherReport, int(report_id)) is None:
        raise WeatherIQError("Report not found.", status_code=404, code="not_found")
    row = NotificationDelivery(
        alert_id=None if alert_id is None else int(alert_id),
        report_id=None if report_id is None else int(report_id),
        channel=channel,
        destination=destination,
        status=status,
        error=payload.get("error"),
        response=payload.get("response"),
        attempted_at=datetime.now(timezone.utc),
    )
    session.add(row)
    if report_id is not None and status == "delivered":
        report = session.get(WeatherReport, int(report_id))
        if report is not None:
            report.delivery_status = "delivered"
    session.flush()
    return {
        "id": row.id,
        "status": row.status,
        "channel": row.channel,
        "duplicate": False,
        "attempted_at": isoformat(row.attempted_at),
    }


def pending_alerts(session: Session) -> list[Alert]:
    alerts = session.query(Alert).filter_by(status="open").order_by(Alert.created_at.asc()).all()
    pending = []
    for alert in alerts:
        delivered = any(item.status == "delivered" for item in alert.deliveries)
        if not delivered:
            pending.append(alert)
    return pending


def store_report(session: Session, payload: dict) -> WeatherReport:
    if not payload.get("body") or not payload.get("title"):
        raise WeatherIQError("title and body are required.", code="invalid_report")
    report = WeatherReport(
        title=str(payload["title"]),
        body=str(payload["body"]),
        format=str(payload.get("format") or "markdown"),
        period_start=_optional_time(payload.get("period_start")),
        period_end=_optional_time(payload.get("period_end")),
        delivery_status="stored",
    )
    session.add(report)
    session.flush()
    return report


def _optional_time(value) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return as_utc(parsed)
