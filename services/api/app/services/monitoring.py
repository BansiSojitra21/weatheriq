from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import IngestionRun, ModelMetadata, ModelPrediction, WeatherObservation
from app.services.catalog import ANOMALY_NOTE, PRECIPITATION_NOTE, TEMPERATURE_NOTE, as_utc, isoformat
from app.services.predictions import external_benchmark


def _public_report(report: dict | None, limitations: str) -> dict | None:
    if report is None:
        return None
    public = dict(report)
    public["limitations"] = limitations
    return public


def _read_report(name: str) -> dict | None:
    path = get_settings().resolved_model_dir() / f"{name}_report.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def monitoring_payload(session: Session) -> dict:
    reports = {name: _read_report(name) for name in ("temperature", "precipitation", "anomaly")}
    metadata = session.query(ModelMetadata).order_by(ModelMetadata.trained_at.desc()).all()
    latest_daily = session.query(func.max(WeatherObservation.observed_at)).filter_by(granularity="daily").scalar()
    latest_hourly = session.query(func.max(WeatherObservation.observed_at)).filter_by(granularity="hourly").scalar()
    latest_ingest = session.query(IngestionRun).order_by(IngestionRun.started_at.desc()).first()
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    recent = (
        session.query(WeatherObservation)
        .filter(
            WeatherObservation.granularity == "daily",
            WeatherObservation.observed_at >= cutoff,
        )
        .all()
    )
    missing = {}
    if recent:
        total = len(recent)
        for column in ("temperature_c", "precipitation_mm", "humidity_pct", "wind_speed_kmh", "pressure_hpa"):
            absent = sum(1 for row in recent if getattr(row, column) is None)
            missing[column] = {"missing_rate": round(absent / total, 4), "rows": total}
    drift = None
    temperature = reports.get("temperature") or {}
    if temperature.get("training_temperature_mean") is not None and recent:
        window = datetime.now(timezone.utc) - timedelta(days=14)
        values = [
            row.temperature_c
            for row in recent
            if as_utc(row.observed_at) >= window and row.temperature_c is not None
        ]
        if values:
            recent_mean = sum(values) / len(values)
            drift = {
                "variable": "temperature_c",
                "recent_14_day_mean": round(recent_mean, 3),
                "training_mean": temperature["training_temperature_mean"],
                "difference": round(recent_mean - temperature["training_temperature_mean"], 3),
                "note": (
                    "Basic indicator: recent 14-day mean minus the training-period mean. "
                    "This is not an automated drift alarm and does not retrain the model."
                ),
            }
    operational = []
    predictions = (
        session.query(ModelPrediction)
        .filter_by(target="temperature_c")
        .order_by(ModelPrediction.valid_at.desc())
        .limit(200)
        .all()
    )
    obs_index = {
        (
            row.location_id,
            row.observed_at.replace(tzinfo=row.observed_at.tzinfo or timezone.utc).date(),
        ): row.temperature_c
        for row in session.query(WeatherObservation).filter_by(granularity="daily").all()
        if row.temperature_c is not None
    }
    for prediction in predictions:
        key = (prediction.location_id, prediction.valid_at.date())
        if key not in obs_index or prediction.predicted_value is None:
            continue
        actual = obs_index[key]
        operational.append(
            {
                "location_id": prediction.location_id,
                "valid_at": isoformat(prediction.valid_at),
                "predicted": prediction.predicted_value,
                "actual": actual,
                "residual": round(actual - prediction.predicted_value, 3),
            }
        )
    return {
        "models": [
            {
                "name": row.name,
                "version": row.version,
                "algorithm": row.algorithm,
                "target": row.target,
                "trained_at": isoformat(row.trained_at),
                "train_start": isoformat(row.train_start),
                "train_end": isoformat(row.train_end),
                "test_start": isoformat(row.test_start),
                "test_end": isoformat(row.test_end),
                "status": row.status,
                "random_seed": row.random_seed,
                "limitations": row.limitations,
            }
            for row in metadata
        ],
        "reports": {
            "temperature": _public_report(reports.get("temperature"), TEMPERATURE_NOTE),
            "precipitation": _public_report(reports.get("precipitation"), PRECIPITATION_NOTE),
            "anomaly": _public_report(reports.get("anomaly"), ANOMALY_NOTE),
        },
        "freshness": {
            "latest_daily_observation": isoformat(latest_daily) if latest_daily else None,
            "latest_hourly_observation": isoformat(latest_hourly) if latest_hourly else None,
            "latest_ingestion_status": None if latest_ingest is None else latest_ingest.status,
            "latest_ingestion_at": None if latest_ingest is None else isoformat(latest_ingest.started_at),
        },
        "missing_data": missing,
        "drift": drift,
        "holdout_residuals": None if temperature is None else temperature.get("residuals_sample"),
        "operational_residuals": operational[:80],
        "operational_residual_note": (
            "These differences are shown only where a stored prediction and a later "
            "daily observation share a date. "
            "They are not the past-accuracy score."
        ),
        "external_benchmark": external_benchmark(session),
        "retraining": "Predictions stay as they are until someone trains them again.",
    }
