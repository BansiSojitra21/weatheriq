from __future__ import annotations

import logging

import joblib
import numpy as np
import pandas as pd
from ml.features import FEATURE_COLUMNS, build_supervised
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import WeatherIQError
from app.db.models import ForecastRun, ForecastValue, Location, ModelMetadata, ModelPrediction, WeatherObservation
from app.services.catalog import (
    PRECIPITATION_NOTE,
    TEMPERATURE_NOTE,
    UNIT_LABELS,
    as_utc,
    convert_precipitation,
    convert_temperature,
    isoformat,
)
from app.services.ingestion import catch_up_daily_history, ensure_fresh_current

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, dict]] = {}


def _refresh_prediction_inputs(session: Session, location: Location) -> None:
    try:
        catch_up_daily_history(session, location)
    except Exception:
        logger.exception("daily_history_catch_up_failed location_id=%s", location.id)
    ensure_fresh_current(session, location)


def _load(name: str) -> tuple[dict, str]:
    path = get_settings().resolved_model_dir() / f"{name}.joblib"
    if not path.exists():
        raise WeatherIQError(
            f"No trained {name} model is available. Run python scripts/bootstrap.py after data ingestion.",
            status_code=503,
            code="model_unavailable",
        )
    mtime = path.stat().st_mtime
    cached = _CACHE.get(name)
    if cached and cached[0] == mtime:
        return cached[1], path.name
    artifact = joblib.load(path)
    required = {"feature_columns", "models", "version", "algorithm"}
    if not required.issubset(artifact):
        raise WeatherIQError(
            f"The {name} artifact is missing required metadata.", status_code=500, code="invalid_artifact"
        )
    if artifact["feature_columns"] != FEATURE_COLUMNS:
        raise WeatherIQError(
            "The saved model features do not match the current feature definition.",
            status_code=500,
            code="feature_mismatch",
        )
    _CACHE[name] = (mtime, artifact)
    return artifact, str(path)


def _daily_frame(session: Session, location: Location) -> pd.DataFrame:
    rows = (
        session.query(WeatherObservation)
        .filter_by(location_id=location.id, granularity="daily")
        .order_by(WeatherObservation.observed_at.asc())
        .all()
    )
    return pd.DataFrame(
        [
            {
                "location_id": location.id,
                "latitude": location.latitude,
                "observed_at": as_utc(row.observed_at),
                "temperature_c": row.temperature_c,
                "precipitation_mm": row.precipitation_mm,
                "humidity_pct": row.humidity_pct,
                "wind_speed_kmh": row.wind_speed_kmh,
                "pressure_hpa": row.pressure_hpa,
                "cloud_cover_pct": row.cloud_cover_pct,
            }
            for row in rows
        ]
    )


def _report(name: str) -> dict | None:
    path = get_settings().resolved_model_dir() / f"{name}_report.json"
    if not path.exists():
        return None
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _store_prediction(session: Session, **values) -> None:
    existing = (
        session.query(ModelPrediction)
        .filter_by(
            model_name=values["model_name"],
            model_version=values["model_version"],
            location_id=values["location_id"],
            issued_at=values["issued_at"],
            valid_at=values["valid_at"],
            target=values["target"],
        )
        .one_or_none()
    )
    if existing is None:
        session.add(ModelPrediction(**values))
    else:
        for key, value in values.items():
            setattr(existing, key, value)
    session.flush()


def _external_daily(session: Session, location_id: int) -> list[ForecastValue]:
    run = (
        session.query(ForecastRun)
        .filter_by(location_id=location_id, provider="open-meteo", model_name="forecast-daily")
        .one_or_none()
    )
    if run is None:
        return []
    return (
        session.query(ForecastValue)
        .filter_by(run_id=run.id, granularity="daily")
        .order_by(ForecastValue.valid_at)
        .all()
    )


def _metadata_id(session: Session, name: str, version: str) -> int | None:
    row = session.query(ModelMetadata).filter_by(name=name, version=version).one_or_none()
    return row.id if row else None


def _fourier_value(row: pd.Series, model: dict) -> float | None:
    bundle = model.get("fourier") or {}
    location_key = str(int(row["location_id"]))
    stored = (bundle.get("models") or {}).get(location_key)
    if stored:
        total = 0.0
        for column in stored["columns"]:
            value = 1.0 if column == "const" else float(row[column])
            total += stored["params"][column] * value
        return float(total)
    doy = int(pd.Timestamp(row["target_time"]).dayofyear)
    clim = (model.get("climatology") or {}).get(f"{int(row['location_id'])}:{doy}")
    if clim is not None:
        return float(clim)
    means = model.get("location_means") or {}
    value = means.get(int(row["location_id"]))
    return None if value is None else float(value)


def predict_temperature(session: Session, location: Location, horizons: list[int], units: str) -> dict:
    _refresh_prediction_inputs(session, location)
    artifact, _path = _load("temperature")
    frame = _daily_frame(session, location)
    if frame.empty:
        raise WeatherIQError("No daily observations are stored for this location.", status_code=409, code="no_data")
    report = _report("temperature")
    external = _external_daily(session, location.id)
    external_by_day = {as_utc(item.valid_at).date(): item for item in external}
    predictions = []
    metadata_id = _metadata_id(session, "temperature", artifact["version"])
    for horizon in horizons:
        key = str(horizon)
        if key not in artifact["models"]:
            raise WeatherIQError(f"Temperature horizon {horizon} is not in the trained model.", code="invalid_horizon")
        supervised = build_supervised(frame, horizon, "temperature_c")
        ready = supervised.dropna(subset=FEATURE_COLUMNS)
        if ready.empty:
            raise WeatherIQError(
                "Not enough recent daily history to build forecast features.",
                status_code=409,
                code="insufficient_history",
            )
        row = ready.iloc[-1]
        model = artifact["models"][key]
        features = pd.DataFrame([row[FEATURE_COLUMNS]])
        predicted = float(model["point"].predict(features)[0])
        lower = float(model["q10"].predict(features)[0])
        upper = float(model["q90"].predict(features)[0])
        if lower > upper:
            lower, upper = upper, lower
        issued_at = row["observed_at"].to_pydatetime()
        valid_at = row["target_time"].to_pydatetime()
        persistence = float(row["temp_lag_1"])
        seasonal = _fourier_value(row, model)
        _store_prediction(
            session,
            model_metadata_id=metadata_id,
            model_name="temperature",
            model_version=artifact["version"],
            location_id=location.id,
            issued_at=as_utc(issued_at),
            valid_at=as_utc(valid_at),
            horizon_days=horizon,
            target="temperature_c",
            predicted_value=predicted,
            lower_value=lower,
            upper_value=upper,
            persistence_value=persistence,
            seasonal_value=seasonal,
        )
        external_row = external_by_day.get(as_utc(valid_at).date())
        holdout = None
        if report:
            holdout = next((item for item in report.get("by_horizon", []) if item["horizon_days"] == horizon), None)
        interval = (holdout or {}).get("interval")
        predictions.append(
            {
                "kind": "ml_prediction",
                "horizon_days": horizon,
                "issued_at": isoformat(as_utc(issued_at)),
                "target_time": isoformat(as_utc(valid_at)),
                "predicted_temperature": convert_temperature(predicted, units),
                "lower": convert_temperature(lower, units),
                "upper": convert_temperature(upper, units),
                "interval": interval,
                "persistence_baseline": convert_temperature(persistence, units),
                "statistical_baseline": convert_temperature(seasonal, units),
                "external_forecast": None
                if external_row is None
                else {
                    "kind": "external_forecast",
                    "provider": "open-meteo",
                    "temperature_min": convert_temperature(external_row.temperature_min_c, units),
                    "temperature_max": convert_temperature(external_row.temperature_max_c, units),
                    "retrieved_at": isoformat(as_utc(external[0].issued_at))
                    if external and external[0].issued_at
                    else None,
                    "note": "Daily high and low from the weather forecast. This is separate from the prediction.",
                },
            }
        )
    return {
        "kind": "ml_prediction",
        "location_id": location.id,
        "units": units,
        "unit_labels": UNIT_LABELS[units],
        "model": {
            "name": "temperature",
            "version": artifact["version"],
            "algorithm": artifact["algorithm"],
        },
        "predictions": predictions,
        "backtest": {
            "label": "Checked on past days that were not used to build the prediction.",
            "by_horizon": None if report is None else report.get("by_horizon"),
            "rolling_origin": None if report is None else report.get("rolling_origin"),
            "validation_use": None if report is None else report.get("validation_use"),
        },
        "external_benchmark": external_benchmark(session),
        "limitations": TEMPERATURE_NOTE,
        "comparison_note": (
            "The prediction uses completed daily weather through the last full day. "
            "The weather forecast beside it is a separate forecast for the same date. "
            "They are shown together for context, not as a scored contest."
        ),
    }


def predict_precipitation(session: Session, location: Location, horizons: list[int], units: str) -> dict:
    _refresh_prediction_inputs(session, location)
    artifact, _path = _load("precipitation")
    frame = _daily_frame(session, location)
    if frame.empty:
        raise WeatherIQError("No daily observations are stored for this location.", status_code=409, code="no_data")
    report = _report("precipitation")
    metadata_id = _metadata_id(session, "precipitation", artifact["version"])
    predictions = []
    for horizon in horizons:
        key = str(horizon)
        if key not in artifact["models"]:
            raise WeatherIQError(
                f"Precipitation horizon {horizon} is not in the trained model.", code="invalid_horizon"
            )
        supervised = build_supervised(frame, horizon, "precipitation_mm")
        ready = supervised.dropna(subset=FEATURE_COLUMNS)
        if ready.empty:
            raise WeatherIQError(
                "Not enough recent daily history to build forecast features.",
                status_code=409,
                code="insufficient_history",
            )
        row = ready.iloc[-1]
        model = artifact["models"][key]
        features = pd.DataFrame([row[FEATURE_COLUMNS]])
        probability = float(model["classifier"].predict_proba(features)[0, 1])
        amount = float(np.clip(model["amount"].predict(features)[0], 0, None))
        issued_at = as_utc(row["observed_at"].to_pydatetime())
        valid_at = as_utc(row["target_time"].to_pydatetime())
        _store_prediction(
            session,
            model_metadata_id=metadata_id,
            model_name="precipitation",
            model_version=artifact["version"],
            location_id=location.id,
            issued_at=issued_at,
            valid_at=valid_at,
            horizon_days=horizon,
            target="precipitation_probability",
            predicted_value=probability,
            lower_value=None,
            upper_value=None,
            persistence_value=1.0 if float(row["precip_lag_1"]) > model["occurrence_mm"] else 0.0,
            seasonal_value=None,
        )
        _store_prediction(
            session,
            model_metadata_id=metadata_id,
            model_name="precipitation",
            model_version=artifact["version"],
            location_id=location.id,
            issued_at=issued_at,
            valid_at=valid_at,
            horizon_days=horizon,
            target="precipitation_mm",
            predicted_value=amount,
            lower_value=None,
            upper_value=None,
            persistence_value=max(0.0, float(row["precip_lag_1"])),
            seasonal_value=None,
        )
        holdout = None
        if report:
            holdout = next((item for item in report.get("by_horizon", []) if item["horizon_days"] == horizon), None)
        predictions.append(
            {
                "kind": "ml_prediction",
                "horizon_days": horizon,
                "issued_at": isoformat(issued_at),
                "target_time": isoformat(valid_at),
                "precipitation_probability": round(probability, 4),
                "precipitation_amount": convert_precipitation(amount, units),
                "decision_threshold": model["decision_threshold"],
                "occurrence_threshold_mm": model["occurrence_mm"],
                "persistence_wet": bool(float(row["precip_lag_1"]) > model["occurrence_mm"]),
                "holdout": holdout,
            }
        )
    return {
        "kind": "ml_prediction",
        "location_id": location.id,
        "units": units,
        "unit_labels": UNIT_LABELS[units],
        "model": {"name": "precipitation", "version": artifact["version"], "algorithm": artifact["algorithm"]},
        "predictions": predictions,
        "backtest": {
            "label": "Checked on past days. The rain cutoff was chosen earlier and then kept fixed.",
            "by_horizon": None if report is None else report.get("by_horizon"),
            "validation_use": None if report is None else report.get("validation_use"),
        },
        "limitations": PRECIPITATION_NOTE,
    }


def external_benchmark(session: Session) -> dict:
    """Score stored previous-run daily forecasts against stored daily observations."""
    leads = []
    observations = session.query(WeatherObservation).filter_by(granularity="daily").all()
    actual = {
        (row.location_id, as_utc(row.observed_at).date()): row.temperature_c
        for row in observations
        if row.temperature_c is not None
    }
    actual_precip = {
        (row.location_id, as_utc(row.observed_at).date()): row.precipitation_mm
        for row in observations
        if row.precipitation_mm is not None
    }
    for lead in (1, 2, 3, 7):
        runs = session.query(ForecastRun).filter_by(provider="open-meteo", model_name=f"previous_day{lead}").all()
        errors = []
        precip_errors = []
        for run in runs:
            values = session.query(ForecastValue).filter_by(run_id=run.id, granularity="daily").all()
            for value in values:
                key = (run.location_id, as_utc(value.valid_at).date())
                if value.temperature_c is not None and key in actual:
                    errors.append(actual[key] - value.temperature_c)
                if value.precipitation_mm is not None and key in actual_precip:
                    precip_errors.append(actual_precip[key] - value.precipitation_mm)
        if not errors:
            leads.append({"lead_days": lead, "available": False, "n": 0})
            continue
        arr = np.asarray(errors, dtype=float)
        precip = np.asarray(precip_errors, dtype=float) if precip_errors else None
        leads.append(
            {
                "lead_days": lead,
                "available": True,
                "n": int(len(arr)),
                "temperature_mae_c": round(float(np.mean(np.abs(arr))), 3),
                "temperature_rmse_c": round(float(np.sqrt(np.mean(arr**2))), 3),
                "precipitation_mae_mm": None if precip is None else round(float(np.mean(np.abs(precip))), 3),
                "precipitation_n": 0 if precip is None else int(len(precip)),
            }
        )
    return {
        "available": any(item.get("available") for item in leads),
        "provider": "open-meteo-previous-runs",
        "kind": "external_forecast_benchmark",
        "by_lead_days": leads,
        "note": (
            "These scores compare an earlier weather forecast, averaged to a daily temperature, "
            "with the temperature later recorded for the same city and date. "
            "Only dates that forecast returned are included. This is separate from the prediction check above."
        ),
    }
