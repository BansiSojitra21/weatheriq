from __future__ import annotations

from datetime import datetime, timedelta, timezone

import joblib
import numpy as np
import pandas as pd
from ml.anomaly import explain, is_flagged, modified_z, reference_bounds
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import WeatherIQError
from app.db.models import AnomalyEvent, Location, WeatherObservation
from app.services.catalog import as_utc, isoformat

VARIABLES = {
    "temperature_c": "temperature_c",
    "precipitation_mm": "precipitation_mm",
    "humidity_pct": "humidity_pct",
    "wind_speed_kmh": "wind_speed_kmh",
    "pressure_hpa": "pressure_hpa",
}


def anomaly_out(event: AnomalyEvent, location_name: str | None = None) -> dict:
    return {
        "id": event.id,
        "location_id": event.location_id,
        "location_name": location_name,
        "variable": event.variable,
        "observed_at": isoformat(event.observed_at),
        "observed_value": event.observed_value,
        "expected_low": event.expected_low,
        "expected_high": event.expected_high,
        "score": event.score,
        "method": event.method,
        "explanation": _plain_explanation(event.explanation),
        "review_status": event.review_status,
        "is_hazard_warning": False,
        "created_at": isoformat(event.created_at),
    }


def _plain_explanation(text: str) -> str:
    replacements = {
        "Isolation Forest, fit only on earlier history, scored": "A pattern check on earlier days scored",
        "Isolation Forest": "pattern check",
        "modified z-score": "unusualness score",
        "robust reference range": "usual range",
        "temperature_c": "Temperature",
        "precipitation_mm": "Rain",
        "humidity_pct": "Humidity",
        "wind_speed_kmh": "Wind",
        "pressure_hpa": "Pressure",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _load_isolation():
    path = get_settings().resolved_model_dir() / "anomaly.joblib"
    if not path.exists():
        return None
    return joblib.load(path)


def detect_anomalies(
    session: Session,
    *,
    location_id: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    variables: list[str] | None = None,
    threshold: float = 3.5,
    window_days: int = 30,
) -> dict:
    selected = variables or list(VARIABLES)
    unknown = [item for item in selected if item not in VARIABLES]
    if unknown:
        raise WeatherIQError(f"Unknown anomaly variables: {unknown}", code="invalid_variable")
    query = session.query(WeatherObservation).filter_by(granularity="daily")
    if location_id is not None:
        query = query.filter_by(location_id=location_id)
    rows = query.order_by(WeatherObservation.observed_at.asc()).all()
    if not rows:
        return {"created_or_updated": 0, "events": [], "note": "No daily observations are stored yet."}
    frame = pd.DataFrame(
        [
            {
                "location_id": row.location_id,
                "observed_at": as_utc(row.observed_at),
                **{name: getattr(row, name) for name in VARIABLES},
            }
            for row in rows
        ]
    )
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    artifact = _load_isolation()
    created = 0
    events: list[AnomalyEvent] = []
    end_bound = end or datetime.now(timezone.utc)
    start_bound = start or (end_bound - timedelta(days=30))
    for loc_id, group in frame.groupby("location_id"):
        group = group.sort_values("observed_at")
        for index, point in group.iterrows():
            observed_at = point["observed_at"].to_pydatetime()
            if observed_at < start_bound or observed_at > end_bound:
                continue
            history = group[group["observed_at"] < point["observed_at"]].tail(window_days)
            methods = []
            explanations = []
            score = None
            low = None
            high = None
            flagged_variable = None
            flagged_value = None
            for variable in selected:
                value = point[variable]
                if pd.isna(value):
                    continue
                bounds = reference_bounds(history[variable].dropna().tolist(), threshold)
                if bounds and is_flagged(float(value), bounds, threshold):
                    z_score = modified_z(float(value), bounds)
                    methods.append("robust_z")
                    explanations.append(explain(variable, float(value), bounds, z_score, threshold))
                    score = float(z_score) if np.isfinite(z_score) else None
                    low = bounds["low"]
                    high = bounds["high"]
                    flagged_variable = variable
                    flagged_value = float(value)
                    break
            isolation_flag = False
            if artifact and flagged_variable is None:
                model = artifact.get("models", {}).get(str(int(loc_id)))
                columns = artifact.get("feature_columns", [])
                if model is not None and all(pd.notna(point[column]) for column in columns):
                    vector = pd.DataFrame([{column: float(point[column]) for column in columns}])
                    prediction = int(model.predict(vector)[0])
                    raw = float(model.decision_function(vector)[0])
                    if prediction == -1:
                        isolation_flag = True
                        methods.append("isolation_forest")
                        score = raw
                        flagged_variable = "multivariate"
                        flagged_value = float(point["temperature_c"]) if pd.notna(point["temperature_c"]) else 0.0
                        explanations.append(
                            "A pattern check on earlier days scored this day's combined "
                            "temperature, rain, humidity, wind, and pressure as unusual "
                            f"(score {raw:.3f}). This is not a hazard warning."
                        )
            if not methods or flagged_variable is None or flagged_value is None:
                continue
            method = "+".join(dict.fromkeys(methods))
            if isolation_flag and "robust_z" in methods:
                method = "robust_z+isolation_forest"
            existing = (
                session.query(AnomalyEvent)
                .filter_by(location_id=int(loc_id), variable=flagged_variable, observed_at=as_utc(observed_at))
                .one_or_none()
            )
            if existing is None:
                existing = AnomalyEvent(
                    location_id=int(loc_id),
                    variable=flagged_variable,
                    observed_at=as_utc(observed_at),
                    observed_value=flagged_value,
                    review_status="unreviewed",
                    is_hazard_warning=False,
                )
                session.add(existing)
            existing.expected_low = low
            existing.expected_high = high
            existing.score = score
            existing.method = method
            existing.explanation = " ".join(explanations)
            existing.is_hazard_warning = False
            events.append(existing)
            created += 1
    session.flush()
    names = {item.id: item.name for item in session.query(Location).all()}
    return {
        "created_or_updated": created,
        "exploratory": True,
        "classification_metrics": None,
        "events": [anomaly_out(event, names.get(event.location_id)) for event in events],
    }


def review_anomaly(session: Session, anomaly_id: int, review_status: str) -> AnomalyEvent:
    if review_status not in {"unreviewed", "confirmed", "rejected"}:
        raise WeatherIQError("Review status must be unreviewed, confirmed, or rejected.", code="invalid_status")
    event = session.get(AnomalyEvent, anomaly_id)
    if event is None:
        raise WeatherIQError("Anomaly not found.", status_code=404, code="not_found")
    event.review_status = review_status
    session.flush()
    return event
