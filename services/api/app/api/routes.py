from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import WeatherIQError
from app.core.security import require_api_key
from app.db.models import Alert, AlertRule, AnomalyEvent, Location, WeatherReport
from app.db.session import check_database, get_db
from app.services.alerts import alert_out, evaluate_rules, rule_out, update_alert_status
from app.services.analytics import (
    correlation,
    history_payload,
    monthly,
    observation_frame,
    seasonal,
    series,
    summary,
    to_csv,
)
from app.services.anomaly_service import anomaly_out, detect_anomalies, review_anomaly
from app.services.catalog import ATTRIBUTION, DISCLAIMER, isoformat
from app.services.ingestion import ensure_fresh_current, ingest_many
from app.services.monitoring import monitoring_payload
from app.services.open_meteo import fetch_json, geocode_url
from app.services.predictions import external_benchmark, predict_precipitation, predict_temperature
from app.services.weather_risk import risk_overview
from app.services.weather_views import current_payload, location_out
from app.services.workflows import accept_weather_event, pending_alerts, record_delivery, store_report

router = APIRouter(prefix="/api/v1")
ALERT_SEVERITIES = {"info", "watch", "warning", "low", "moderate", "high", "critical"}


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    country: str = ""
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = "UTC"
    is_default: bool = False


class PredictionIn(BaseModel):
    location_id: int
    horizons: list[int] = Field(default_factory=lambda: [1])
    units: str = "metric"


class AnomalyIn(BaseModel):
    location_id: int | None = None
    start: datetime | None = None
    end: datetime | None = None
    variables: list[str] | None = None
    threshold: float = Field(default=3.5, ge=2, le=10)
    window_days: int = Field(default=30, ge=14, le=120)


class ReviewIn(BaseModel):
    review_status: str


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    location_id: int | None = None
    variable: str
    operator: str
    threshold: float
    severity: str = "watch"
    enabled: bool = True
    cooldown_minutes: int = Field(default=720, ge=0, le=10080)
    description: str = ""


class RulePatch(BaseModel):
    name: str | None = None
    threshold: float | None = None
    severity: str | None = None
    enabled: bool | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0, le=10080)
    description: str | None = None


class AlertPatch(BaseModel):
    status: str


class RiskIn(BaseModel):
    location_id: int | None = None


class IngestionIn(BaseModel):
    location_id: int | None = None
    kinds: list[str] = Field(default_factory=lambda: ["current", "forecast"])
    history_days: int | None = Field(default=None, ge=30, le=3650)
    hourly_days: int | None = Field(default=None, ge=1, le=92)


class WorkflowEventIn(BaseModel):
    event_id: str
    location_id: int
    timestamp: str
    source: str
    variable: str | None = None
    actual_value: float | None = None
    threshold: float | None = None
    severity: str | None = None
    rule_name: str | None = None
    message: str | None = None
    condition_kind: str | None = None


class DeliveryIn(BaseModel):
    alert_id: int | None = None
    report_id: int | None = None
    channel: str = "test"
    destination: str = ""
    status: str
    error: str | None = None
    response: dict | None = None


class ReportIn(BaseModel):
    title: str
    body: str
    format: str = "markdown"
    period_start: str | None = None
    period_end: str | None = None


def units_param(units: str = Query("metric")) -> str:
    if units not in {"metric", "imperial"}:
        raise WeatherIQError("units must be metric or imperial.", code="invalid_units")
    return units


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    if end < start:
        raise WeatherIQError("end must be on or after start.", code="invalid_range")
    if (end - start).days > 1825:
        raise WeatherIQError("Date range cannot exceed 5 years.", code="invalid_range")
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)
    return start_dt, end_dt


def _location(session: Session, location_id: int) -> Location:
    location = session.get(Location, location_id)
    if location is None:
        raise WeatherIQError("Location not found.", status_code=404, code="not_found")
    return location


@router.get("/health")
def health(session: Session = Depends(get_db)) -> dict:
    database = "ok"
    try:
        check_database()
    except Exception as exc:
        database = f"error: {exc}"
    model_dir = __import__("app.core.config", fromlist=["get_settings"]).get_settings().resolved_model_dir()
    artifacts = {name: (model_dir / f"{name}.joblib").exists() for name in ("temperature", "precipitation", "anomaly")}
    status = "ok" if database == "ok" else "degraded"
    if not all(artifacts.values()):
        status = "degraded" if database == "ok" else status
    return {
        "status": status,
        "database": database,
        "model_artifacts": artifacts,
        "version": "1.0.0",
        "disclaimer": DISCLAIMER,
    }


@router.get("/locations")
def list_locations(session: Session = Depends(get_db)) -> dict:
    rows = session.query(Location).order_by(Location.name).all()
    return {"items": [location_out(row) for row in rows]}


@router.post("/locations", dependencies=[Depends(require_api_key)])
def create_location(body: LocationIn, session: Session = Depends(get_db)) -> dict:
    if body.is_default:
        for row in session.query(Location).all():
            row.is_default = False
    location = Location(**body.model_dump())
    session.add(location)
    session.flush()
    return location_out(location)


@router.get("/geocode")
def geocode(q: str = Query(min_length=2), session: Session = Depends(get_db)) -> dict:
    del session
    try:
        payload = fetch_json(geocode_url(q), ttl=timedelta(hours=12))
    except Exception as exc:
        raise WeatherIQError(f"Geocoding failed: {exc}", status_code=502, code="provider_error") from exc
    items = []
    for result in payload.get("results") or []:
        items.append(
            {
                "name": result.get("name"),
                "country": result.get("country"),
                "admin1": result.get("admin1"),
                "latitude": result.get("latitude"),
                "longitude": result.get("longitude"),
                "timezone": result.get("timezone"),
            }
        )
    return {"items": items, "attribution": ATTRIBUTION}


@router.get("/weather/current")
def weather_current(
    location_id: int,
    units: str = Depends(units_param),
    session: Session = Depends(get_db),
) -> dict:
    location = _location(session, location_id)
    ensure_fresh_current(session, location)
    return current_payload(session, location, units)


@router.get("/weather/history")
def weather_history(
    location_id: int,
    start: date,
    end: date,
    granularity: str = Query("daily"),
    units: str = Depends(units_param),
    session: Session = Depends(get_db),
) -> dict:
    if granularity not in {"daily", "hourly"}:
        raise WeatherIQError("granularity must be daily or hourly.", code="invalid_granularity")
    start_dt, end_dt = _bounds(start, end)
    if granularity == "hourly" and (end - start).days > 120:
        raise WeatherIQError("Hourly history is limited to 120 days.", code="invalid_range")
    frame = observation_frame(session, location_id, start_dt, end_dt, granularity)
    _location(session, location_id)
    return history_payload(frame, units, location_id, start_dt, end_dt, granularity)


@router.get("/weather/forecast")
def weather_forecast(
    location_id: int,
    units: str = Depends(units_param),
    session: Session = Depends(get_db),
) -> dict:
    location = _location(session, location_id)
    ensure_fresh_current(session, location)
    payload = current_payload(session, location, units)
    return {
        "location": payload["location"],
        "kind": "external_forecast",
        "provider": "open-meteo",
        "issuance_basis": "retrieval_time",
        "hourly": payload["hourly"],
        "daily": payload["daily"],
        "freshness": payload["freshness"],
        "attribution": ATTRIBUTION,
        "note": "These values are the weather forecast, not WeatherIQ predictions.",
    }


@router.get("/analytics/summary")
def analytics_summary(
    location_id: int,
    start: date,
    end: date,
    units: str = Depends(units_param),
    session: Session = Depends(get_db),
) -> dict:
    start_dt, end_dt = _bounds(start, end)
    frame = observation_frame(session, location_id, start_dt, end_dt, "daily")
    payload = summary(frame, units)
    payload.update(
        {
            "location_id": location_id,
            "start": isoformat(start_dt),
            "end": isoformat(end_dt),
            "kind": "observation",
            "monthly": monthly(frame, units),
            "seasonal": seasonal(frame, units),
            "season_note": (
                "Meteorological seasons pool every matching month in the selected range. "
                "December is grouped with January and February."
            ),
        }
    )
    return payload


@router.get("/analytics/trends")
def analytics_trends(
    location_id: int,
    start: date,
    end: date,
    variable: str = "temperature",
    compare_location_id: int | None = None,
    units: str = Depends(units_param),
    session: Session = Depends(get_db),
) -> dict:
    if variable not in {"temperature", "precipitation", "humidity", "wind_speed", "pressure", "cloud_cover"}:
        raise WeatherIQError("Unknown weather variable.", code="invalid_variable")
    start_dt, end_dt = _bounds(start, end)
    frame = observation_frame(session, location_id, start_dt, end_dt, "daily")
    payload = {
        "location_id": location_id,
        "variable": variable,
        "units": units,
        "start": isoformat(start_dt),
        "end": isoformat(end_dt),
        "kind": "observation",
        "series": series(frame, units, variable),
        "rolling_window_days": 7,
    }
    if compare_location_id is not None:
        other = observation_frame(session, compare_location_id, start_dt, end_dt, "daily")
        payload["comparison"] = {
            "location_id": compare_location_id,
            "series": series(other, units, variable),
        }
    return payload


@router.get("/analytics/correlation")
def analytics_correlation(
    location_id: int,
    start: date,
    end: date,
    session: Session = Depends(get_db),
) -> dict:
    start_dt, end_dt = _bounds(start, end)
    frame = observation_frame(session, location_id, start_dt, end_dt, "daily")
    payload = correlation(frame)
    payload["location_id"] = location_id
    payload["start"] = isoformat(start_dt)
    payload["end"] = isoformat(end_dt)
    return payload


@router.get("/analytics/export")
def analytics_export(
    location_id: int,
    start: date,
    end: date,
    units: str = Depends(units_param),
    session: Session = Depends(get_db),
) -> Response:
    start_dt, end_dt = _bounds(start, end)
    frame = observation_frame(session, location_id, start_dt, end_dt, "daily")
    content = to_csv(frame, units)
    return PlainTextResponse(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="weatheriq-{location_id}.csv"'},
    )


@router.post("/predictions/temperature", dependencies=[Depends(require_api_key)])
def temperature_prediction(body: PredictionIn, session: Session = Depends(get_db)) -> dict:
    if body.units not in {"metric", "imperial"}:
        raise WeatherIQError("units must be metric or imperial.", code="invalid_units")
    return predict_temperature(session, _location(session, body.location_id), body.horizons, body.units)


@router.post("/predictions/precipitation", dependencies=[Depends(require_api_key)])
def precipitation_prediction(body: PredictionIn, session: Session = Depends(get_db)) -> dict:
    if body.units not in {"metric", "imperial"}:
        raise WeatherIQError("units must be metric or imperial.", code="invalid_units")
    return predict_precipitation(session, _location(session, body.location_id), body.horizons, body.units)


@router.get("/predictions/backtest")
def prediction_backtest(session: Session = Depends(get_db)) -> dict:
    from app.services.predictions import _report

    return {
        "temperature": _report("temperature"),
        "precipitation": _report("precipitation"),
        "external_benchmark": external_benchmark(session),
        "note": "Holdout metrics come from training reports. They are not recomputed on training rows at request time.",
    }


@router.post("/anomalies/detect", dependencies=[Depends(require_api_key)])
def anomalies_detect(body: AnomalyIn, session: Session = Depends(get_db)) -> dict:
    return detect_anomalies(
        session,
        location_id=body.location_id,
        start=body.start,
        end=body.end,
        variables=body.variables,
        threshold=body.threshold,
        window_days=body.window_days,
    )


@router.get("/anomalies")
def list_anomalies(
    location_id: int | None = None,
    variable: str | None = None,
    review_status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> dict:
    query = session.query(AnomalyEvent)
    if location_id is not None:
        query = query.filter_by(location_id=location_id)
    if variable:
        query = query.filter_by(variable=variable)
    if review_status:
        query = query.filter_by(review_status=review_status)
    total = query.count()
    rows = query.order_by(AnomalyEvent.observed_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    names = {item.id: item.name for item in session.query(Location).all()}
    return {
        "items": [anomaly_out(row, names.get(row.location_id)) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "exploratory": True,
        "note": "Flags are unusual values relative to recent history. They are not hazard warnings.",
    }


@router.patch("/anomalies/{anomaly_id}", dependencies=[Depends(require_api_key)])
def patch_anomaly(anomaly_id: int, body: ReviewIn, session: Session = Depends(get_db)) -> dict:
    event = review_anomaly(session, anomaly_id, body.review_status)
    location = session.get(Location, event.location_id)
    return anomaly_out(event, None if location is None else location.name)


@router.post("/risk/evaluate", dependencies=[Depends(require_api_key)])
def risk_evaluate(body: RiskIn, session: Session = Depends(get_db)) -> dict:
    return evaluate_rules(session, body.location_id)


@router.get("/risk/overview")
def risk_overview_route(session: Session = Depends(get_db)) -> dict:
    return risk_overview(session)


@router.get("/alerts")
def list_alerts(
    status: str | None = None,
    severity: str | None = None,
    location_id: int | None = None,
    unnotified: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> dict:
    if unnotified:
        rows = pending_alerts(session)
        if status:
            rows = [row for row in rows if row.status == status]
        if severity:
            rows = [row for row in rows if row.severity == severity]
        if location_id is not None:
            rows = [row for row in rows if row.location_id == location_id]
        total = len(rows)
        page_rows = rows[(page - 1) * page_size : page * page_size]
    else:
        query = session.query(Alert)
        if status:
            query = query.filter_by(status=status)
        if severity:
            query = query.filter_by(severity=severity)
        if location_id is not None:
            query = query.filter_by(location_id=location_id)
        total = query.count()
        page_rows = query.order_by(Alert.event_time.desc()).offset((page - 1) * page_size).limit(page_size).all()
    names = {item.id: item.name for item in session.query(Location).all()}
    return {
        "items": [alert_out(row, names.get(row.location_id)) for row in page_rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/alerts/rules", dependencies=[Depends(require_api_key)])
def create_rule(body: RuleIn, session: Session = Depends(get_db)) -> dict:
    if body.operator not in {"gt", "gte", "lt", "lte"}:
        raise WeatherIQError("operator must be gt, gte, lt, or lte.", code="invalid_operator")
    if body.severity not in ALERT_SEVERITIES:
        raise WeatherIQError("severity must be low, moderate, high, or critical.", code="invalid_severity")
    if body.location_id is not None:
        _location(session, body.location_id)
    rule = AlertRule(**body.model_dump())
    session.add(rule)
    session.flush()
    location_id = body.location_id
    evaluation = evaluate_rules(session, location_id)
    return {**rule_out(rule), "evaluation": evaluation}


@router.get("/alerts/rules")
def list_rules(session: Session = Depends(get_db)) -> dict:
    rows = session.query(AlertRule).order_by(AlertRule.id).all()
    return {"items": [rule_out(row) for row in rows]}


@router.patch("/alerts/rules/{rule_id}", dependencies=[Depends(require_api_key)])
def patch_rule(rule_id: int, body: RulePatch, session: Session = Depends(get_db)) -> dict:
    rule = session.get(AlertRule, rule_id)
    if rule is None:
        raise WeatherIQError("Rule not found.", status_code=404, code="not_found")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("severity") is not None and changes["severity"] not in ALERT_SEVERITIES:
        raise WeatherIQError("severity must be low, moderate, high, or critical.", code="invalid_severity")
    for key, value in changes.items():
        setattr(rule, key, value)
    rule.updated_at = datetime.now(timezone.utc)
    session.flush()
    evaluation = evaluate_rules(session, rule.location_id) if changes.get("enabled") is True else None
    return {**rule_out(rule), "evaluation": evaluation}


@router.patch("/alerts/{alert_id}", dependencies=[Depends(require_api_key)])
def patch_alert(alert_id: int, body: AlertPatch, session: Session = Depends(get_db)) -> dict:
    alert = update_alert_status(session, alert_id, body.status)
    location = session.get(Location, alert.location_id)
    return alert_out(alert, None if location is None else location.name)


@router.post("/workflows/weather-event", dependencies=[Depends(require_api_key)])
def workflow_event(body: WorkflowEventIn, session: Session = Depends(get_db)) -> dict:
    return accept_weather_event(session, body.model_dump())


@router.post("/workflows/delivery", dependencies=[Depends(require_api_key)])
def workflow_delivery(body: DeliveryIn, session: Session = Depends(get_db)) -> dict:
    return record_delivery(session, body.model_dump())


@router.get("/workflows/pending", dependencies=[Depends(require_api_key)])
def workflow_pending(session: Session = Depends(get_db)) -> dict:
    rows = pending_alerts(session)
    names = {item.id: item.name for item in session.query(Location).all()}
    return {"items": [alert_out(row, names.get(row.location_id)) for row in rows], "pending_count": len(rows)}


@router.post("/ingestion/run", dependencies=[Depends(require_api_key)])
def ingestion_run(body: IngestionIn, session: Session = Depends(get_db)) -> dict:
    query = session.query(Location)
    if body.location_id is not None:
        query = query.filter_by(id=body.location_id)
    locations = query.all()
    if not locations:
        raise WeatherIQError("No locations to ingest.", status_code=404, code="not_found")
    summaries = ingest_many(
        session,
        locations,
        kinds=set(body.kinds),
        history_days=body.history_days,
        hourly_days=body.hourly_days,
    )
    return {"runs": summaries}


@router.get("/monitoring")
def monitoring(session: Session = Depends(get_db)) -> dict:
    return monitoring_payload(session)


@router.get("/models")
def models(session: Session = Depends(get_db)) -> dict:
    payload = monitoring_payload(session)
    return {"items": payload["models"]}


@router.post("/reports", dependencies=[Depends(require_api_key)])
def create_report(body: ReportIn, session: Session = Depends(get_db)) -> dict:
    report = store_report(session, body.model_dump())
    return {
        "id": report.id,
        "title": report.title,
        "delivery_status": report.delivery_status,
        "created_at": isoformat(report.created_at),
    }


@router.get("/reports/latest")
def latest_report(session: Session = Depends(get_db)) -> dict:
    report = session.query(WeatherReport).order_by(WeatherReport.created_at.desc()).first()
    if report is None:
        return {"report": None}
    return {
        "report": {
            "id": report.id,
            "title": report.title,
            "body": report.body,
            "format": report.format,
            "delivery_status": report.delivery_status,
            "created_at": isoformat(report.created_at),
        }
    }
