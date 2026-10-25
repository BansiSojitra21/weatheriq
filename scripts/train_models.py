"""Train models from stored daily observations and write artifacts plus database metadata."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "api"))

import pandas as pd
from ml.train import (
    ANOMALY_LIMITATIONS,
    PRECIPITATION_LIMITATIONS,
    TEMPERATURE_LIMITATIONS,
    save_bundle,
    train_anomaly_model,
    train_precipitation_model,
    train_temperature_model,
)

from app.core.config import get_settings
from app.db import session as db_session
from app.db.models import Location, ModelMetadata, WeatherObservation


def _frame(session) -> pd.DataFrame:
    locations = {row.id: row for row in session.query(Location).all()}
    observations = session.query(WeatherObservation).filter_by(granularity="daily").all()
    rows = []
    for row in observations:
        location = locations.get(row.location_id)
        if location is None:
            continue
        rows.append(
            {
                "location_id": row.location_id,
                "latitude": location.latitude,
                "name": location.name,
                "observed_at": row.observed_at,
                "temperature_c": row.temperature_c,
                "precipitation_mm": row.precipitation_mm,
                "humidity_pct": row.humidity_pct,
                "wind_speed_kmh": row.wind_speed_kmh,
                "pressure_hpa": row.pressure_hpa,
                "cloud_cover_pct": row.cloud_cover_pct,
            }
        )
    return pd.DataFrame(rows)


def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _store(session, report: dict, artifact_path: Path, limitations: str) -> None:
    split = (report.get("by_horizon") or [{}])[0].get("split") or report
    train = (split or {}).get("train") or {}
    test = (split or {}).get("test") or {}
    if report["name"] == "anomaly":
        train = {"start": None, "end": report.get("train_end")}
        test = {}
    existing = session.query(ModelMetadata).filter_by(name=report["name"], version=report["version"]).one_or_none()
    if existing is None:
        existing = ModelMetadata(name=report["name"], version=report["version"], artifact_path=str(artifact_path))
        session.add(existing)
    existing.algorithm = report.get("algorithm", "exploratory")
    existing.target = report.get("target", report["name"])
    existing.metrics = report
    existing.feature_names = report.get("feature_columns")
    existing.limitations = limitations
    existing.artifact_path = str(artifact_path)
    existing.train_start = _when(train.get("start"))
    existing.train_end = _when(train.get("end") or report.get("train_end"))
    existing.test_start = _when(test.get("start"))
    existing.test_end = _when(test.get("end"))
    existing.trained_at = _when(report.get("trained_at")) or datetime.now().astimezone()
    existing.random_seed = int(report.get("seed", 42))
    existing.status = "succeeded"


def train_from_database() -> dict:
    db_session.init_database()
    assert db_session.SessionLocal is not None
    session = db_session.SessionLocal()
    try:
        frame = _frame(session)
        if frame.empty or frame["temperature_c"].notna().sum() < 120:
            raise SystemExit("Not enough daily observations to train. Ingest history first.")
        settings = get_settings()
        model_dir = settings.resolved_model_dir()
        temperature = train_temperature_model(frame, algorithm="auto", seed=settings.random_seed, compute_shap=True)
        precipitation = train_precipitation_model(frame, algorithm="auto", seed=settings.random_seed)
        anomaly = train_anomaly_model(frame, seed=settings.random_seed)
        bundles = {
            "temperature": (temperature, TEMPERATURE_LIMITATIONS),
            "precipitation": (precipitation, PRECIPITATION_LIMITATIONS),
            "anomaly": (anomaly, ANOMALY_LIMITATIONS),
        }
        for name, (bundle, limitations) in bundles.items():
            artifact_path = model_dir / f"{name}.joblib"
            report_path = model_dir / f"{name}_report.json"
            save_bundle(artifact_path, bundle["artifact"])
            report_path.write_text(json.dumps(bundle["report"], indent=2), encoding="utf-8")
            _store(session, bundle["report"], artifact_path, limitations)
        session.commit()
        return {name: bundle[0]["report"]["version"] for name, bundle in bundles.items()}
    finally:
        session.close()


if __name__ == "__main__":
    print(json.dumps(train_from_database(), indent=2))
