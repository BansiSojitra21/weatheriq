from __future__ import annotations

import logging
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    IsolationForest,
)
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    mean_absolute_error,
    precision_score,
    recall_score,
    root_mean_squared_error,
)

from ml.features import FEATURE_COLUMNS, build_supervised
from ml.splits import chronological_split

logger = logging.getLogger(__name__)

TEMPERATURE_LIMITATIONS = (
    "This temperature prediction uses recent daily weather for this city. "
    "It is issued after a day is complete and uses only information available then. "
    "It is not an official forecast. Average error is checked on past days that were not used to build it. "
    "The likely range is an estimate from those past days, not a guarantee. "
    "Nothing is claimed beyond the trained 1 to 7 day range."
)
PRECIPITATION_LIMITATIONS = (
    "The experimental rain classifier uses recent daily totals and defines a wet day as above 0.1 mm. "
    "Its probabilities are not necessarily calibrated and should not be treated as an operational weather forecast. "
    "Rainfall amounts cannot go below zero. This is not a flood warning."
)
ANOMALY_LIMITATIONS = (
    "A flag means the measurement looks unusual compared with recent days or a pattern check "
    "fit on earlier data. It does not mean the weather is dangerous."
)


def resolve_algorithm(requested: str) -> str:
    if requested == "sklearn":
        return "sklearn"
    if requested == "lightgbm":
        import lightgbm  # noqa: F401

        return "lightgbm"
    try:
        import lightgbm  # noqa: F401

        return "lightgbm"
    except Exception as exc:
        logger.info("LightGBM is unavailable (%s); using scikit-learn HistGradientBoosting.", exc)
        return "sklearn"


def _regressor(algorithm: str, n_estimators: int, seed: int, quantile: float | None = None):
    if algorithm == "lightgbm":
        import lightgbm as lgb

        params = dict(
            n_estimators=n_estimators,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.9,
            subsample_freq=1,
            colsample_bytree=0.9,
            random_state=seed,
            verbosity=-1,
        )
        if quantile is None:
            return lgb.LGBMRegressor(**params)
        return lgb.LGBMRegressor(objective="quantile", alpha=quantile, **params)
    params = dict(
        max_iter=n_estimators,
        learning_rate=0.05,
        max_leaf_nodes=31,
        min_samples_leaf=20,
        random_state=seed,
    )
    if quantile is None:
        return HistGradientBoostingRegressor(loss="squared_error", **params)
    return HistGradientBoostingRegressor(loss="quantile", quantile=quantile, **params)


def _classifier(algorithm: str, n_estimators: int, seed: int, scale_pos_weight: float):
    if algorithm == "lightgbm":
        import lightgbm as lgb

        return lgb.LGBMClassifier(
            n_estimators=n_estimators,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.9,
            subsample_freq=1,
            colsample_bytree=0.9,
            scale_pos_weight=scale_pos_weight,
            random_state=seed,
            verbosity=-1,
        )
    return HistGradientBoostingClassifier(
        max_iter=n_estimators,
        learning_rate=0.05,
        max_leaf_nodes=31,
        min_samples_leaf=20,
        random_state=seed,
        class_weight="balanced",
    )


def _regression(y_true, y_pred) -> dict:
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(root_mean_squared_error(y_true, y_pred)),
        "n": int(len(y_true)),
    }


def _skill(model_mae: float, baseline_mae: float | None) -> float | None:
    if baseline_mae is None or baseline_mae == 0 or np.isnan(baseline_mae):
        return None
    return float(1 - model_mae / baseline_mae)


def _period(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"start": None, "end": None, "rows": 0}
    return {
        "start": frame["observed_at"].min().isoformat(),
        "end": frame["observed_at"].max().isoformat(),
        "rows": int(len(frame)),
    }


def _fit_fourier(train: pd.DataFrame) -> dict:
    stored: dict[str, dict] = {}
    notes: list[str] = []
    for location_id, group in train.groupby("location_id"):
        if len(group) < 40:
            notes.append(f"Location {location_id} has too few training rows for Fourier regression.")
            continue
        design = sm.add_constant(
            group[["sin_doy", "cos_doy", "sin_doy2", "cos_doy2", "temp_lag_1"]],
            has_constant="add",
        )
        try:
            result = sm.OLS(group["target"].astype(float), design, missing="drop").fit()
        except Exception as exc:
            notes.append(f"Fourier fit failed for location {location_id}: {exc}")
            continue
        stored[str(int(location_id))] = {
            "params": {str(key): float(value) for key, value in result.params.to_dict().items()},
            "columns": [str(column) for column in design.columns],
        }
    return {"models": stored, "notes": notes}


def _predict_fourier(row: pd.Series, bundle: dict, climatology: dict, location_means: dict) -> float:
    location_key = str(int(row["location_id"]))
    model = bundle["models"].get(location_key)
    if model:
        total = 0.0
        for column in model["columns"]:
            value = 1.0 if column == "const" else float(row[column])
            total += model["params"][column] * value
        return float(total)
    doy = int(pd.Timestamp(row["target_time"]).dayofyear)
    seasonal = climatology.get((int(row["location_id"]), doy))
    if seasonal is not None:
        return float(seasonal)
    return float(location_means.get(int(row["location_id"]), np.nan))


def _climatology(train: pd.DataFrame) -> tuple[dict, dict]:
    work = train.copy()
    work["target_doy"] = work["target_time"].dt.dayofyear
    table = work.groupby(["location_id", "target_doy"])["target"].mean().to_dict()
    means = work.groupby("location_id")["target"].mean().to_dict()
    clim = {(int(key[0]), int(key[1])): float(value) for key, value in table.items()}
    loc_means = {int(key): float(value) for key, value in means.items()}
    return clim, loc_means


def _importance(model, columns: list[str]) -> dict[str, float] | None:
    values = getattr(model, "feature_importances_", None)
    if values is None:
        return None
    return {columns[index]: float(values[index]) for index in range(len(columns))}


def _shap_summary(model, features: pd.DataFrame) -> dict:
    try:
        import shap

        sample = features.sample(n=min(120, len(features)), random_state=42)
        explainer = shap.TreeExplainer(model)
        values = np.asarray(explainer.shap_values(sample))
        if values.ndim == 3:
            values = values[0]
        mean_abs = np.abs(values).mean(axis=0)
        return {
            "available": True,
            "sample_rows": int(len(sample)),
            "mean_absolute": {
                features.columns[index]: float(mean_abs[index]) for index in range(len(features.columns))
            },
        }
    except Exception as exc:
        return {"available": False, "reason": str(exc)}


def _slice(frame: pd.DataFrame, dates: list[datetime]) -> pd.DataFrame:
    wanted = pd.DatetimeIndex(pd.to_datetime(list(dates), utc=True))
    observed = pd.to_datetime(frame["observed_at"], utc=True)
    return frame.loc[observed.isin(wanted)].copy()


def train_temperature_model(
    observations: pd.DataFrame,
    *,
    algorithm: str = "auto",
    seed: int = 42,
    n_estimators: int = 300,
    min_train_rows: int = 80,
    compute_shap: bool = False,
    horizons: tuple[int, ...] = (1, 2, 3, 7),
) -> dict:
    chosen = resolve_algorithm(algorithm)
    np.random.seed(seed)
    by_horizon = []
    models: dict[str, dict] = {}
    residuals: list[dict] = []
    by_location: list[dict] = []
    rolling = {"status": "not_run"}
    primary_split = None
    feature_importance = None
    shap_summary = None
    fourier_bundle = None

    for horizon in horizons:
        supervised = build_supervised(observations, horizon, "temperature_c")
        supervised = supervised.dropna(subset=[*FEATURE_COLUMNS, "target"]).copy()
        dates = list(supervised["observed_at"].drop_duplicates())
        train_dates, val_dates, test_dates = chronological_split(dates)
        train = _slice(supervised, train_dates)
        validation = _slice(supervised, val_dates)
        test = _slice(supervised, test_dates)
        if len(train) < min_train_rows:
            raise ValueError(
                f"Temperature horizon {horizon} has {len(train)} training rows; need at least {min_train_rows}."
            )
        point = _regressor(chosen, n_estimators, seed)
        point.fit(train[FEATURE_COLUMNS], train["target"])
        q10 = _regressor(chosen, n_estimators, seed, quantile=0.1)
        q90 = _regressor(chosen, n_estimators, seed, quantile=0.9)
        q10.fit(train[FEATURE_COLUMNS], train["target"])
        q90.fit(train[FEATURE_COLUMNS], train["target"])
        fourier = _fit_fourier(train)
        climatology, location_means = _climatology(train)

        def predict_bundle(frame: pd.DataFrame) -> pd.DataFrame:
            out = frame.copy()
            out["predicted"] = point.predict(out[FEATURE_COLUMNS])
            lower = q10.predict(out[FEATURE_COLUMNS])
            upper = q90.predict(out[FEATURE_COLUMNS])
            out["lower"] = np.minimum(lower, upper)
            out["upper"] = np.maximum(lower, upper)
            out["persistence"] = out["temp_lag_1"]
            out["fourier"] = [_predict_fourier(row, fourier, climatology, location_means) for _, row in out.iterrows()]
            return out

        test_pred = predict_bundle(test)
        val_pred = predict_bundle(validation)
        test_metrics = _regression(test_pred["target"], test_pred["predicted"])
        val_metrics = _regression(val_pred["target"], val_pred["predicted"])
        persistence = _regression(test_pred["target"], test_pred["persistence"])
        fourier_metrics = _regression(test_pred["target"], test_pred["fourier"])
        coverage = float(
            np.mean((test_pred["target"] >= test_pred["lower"]) & (test_pred["target"] <= test_pred["upper"]))
        )
        by_horizon.append(
            {
                "horizon_days": horizon,
                "test": test_metrics,
                "validation": val_metrics,
                "persistence_test": persistence,
                "fourier_test": fourier_metrics,
                "skill_vs_persistence": _skill(test_metrics["mae"], persistence["mae"]),
                "skill_vs_fourier": _skill(test_metrics["mae"], fourier_metrics["mae"]),
                "interval": {
                    "nominal": "model 10th-90th percentile",
                    "test_coverage": coverage,
                    "n": int(len(test_pred)),
                    "note": "Empirical holdout coverage. Not a calibrated prediction interval.",
                },
                "split": {
                    "train": _period(train),
                    "validation": _period(validation),
                    "test": _period(test),
                },
            }
        )
        models[str(horizon)] = {
            "point": point,
            "q10": q10,
            "q90": q90,
            "fourier": fourier,
            "climatology": {f"{loc}:{doy}": value for (loc, doy), value in climatology.items()},
            "location_means": location_means,
        }
        if horizon == horizons[0]:
            primary_split = by_horizon[-1]["split"]
            feature_importance = _importance(point, FEATURE_COLUMNS)
            if compute_shap:
                shap_summary = _shap_summary(point, test[FEATURE_COLUMNS])
            fourier_bundle = fourier
            rolling = _rolling_origin(supervised, chosen, n_estimators, seed, min_train_rows)
        sample = test_pred.sample(n=min(80, len(test_pred)), random_state=seed)
        for _, row in sample.iterrows():
            residuals.append(
                {
                    "location_id": int(row["location_id"]),
                    "horizon_days": horizon,
                    "issued_at": pd.Timestamp(row["observed_at"]).isoformat(),
                    "target_time": pd.Timestamp(row["target_time"]).isoformat(),
                    "actual": float(row["target"]),
                    "predicted": float(row["predicted"]),
                    "residual": float(row["target"] - row["predicted"]),
                    "split": "chronological_holdout",
                }
            )
        for location_id, group in test_pred.groupby("location_id"):
            metrics = _regression(group["target"], group["predicted"])
            by_location.append({"location_id": int(location_id), "horizon_days": horizon, **metrics})

    version = datetime.now(timezone.utc).strftime("ti-%Y%m%dT%H%M%SZ")
    artifact = {
        "kind": "temperature",
        "algorithm": chosen,
        "version": version,
        "seed": seed,
        "feature_columns": FEATURE_COLUMNS,
        "horizons": list(horizons),
        "models": models,
        "n_estimators": n_estimators,
    }
    report = {
        "name": "temperature",
        "version": version,
        "algorithm": chosen,
        "target": "daily_mean_temperature_c",
        "seed": seed,
        "feature_columns": FEATURE_COLUMNS,
        "by_horizon": by_horizon,
        "by_location": by_location,
        "residuals_sample": residuals,
        "rolling_origin": rolling,
        "feature_importance": feature_importance,
        "shap": shap_summary,
        "fourier_notes": (fourier_bundle or {}).get("notes", []),
        "primary_split": primary_split,
        "training_temperature_mean": float(observations["temperature_c"].dropna().mean()),
        "training_temperature_std": float(observations["temperature_c"].dropna().std()),
        "limitations": TEMPERATURE_LIMITATIONS,
        "validation_use": "Validation metrics are reported and were not used to fit or select the temperature model.",
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"artifact": artifact, "report": report}


def _rolling_origin(
    supervised: pd.DataFrame, algorithm: str, n_estimators: int, seed: int, min_train_rows: int
) -> dict:
    dates = sorted(supervised["observed_at"].drop_duplicates())
    count = len(dates)
    block = max(14, count // 10)
    if count < 120:
        return {"status": "skipped", "reason": "Fewer than 120 issuance dates."}
    folds = []
    starts = range(count - 3 * block, count - block + 1, block)
    for start in starts:
        if start < min_train_rows:
            continue
        train = _slice(supervised, list(dates[:start]))
        test = _slice(supervised, list(dates[start : start + block]))
        train = train.dropna(subset=[*FEATURE_COLUMNS, "target"])
        test = test.dropna(subset=[*FEATURE_COLUMNS, "target"])
        if len(train) < min_train_rows or test.empty:
            continue
        model = _regressor(algorithm, max(50, n_estimators // 2), seed)
        model.fit(train[FEATURE_COLUMNS], train["target"])
        predicted = model.predict(test[FEATURE_COLUMNS])
        folds.append(
            {
                "train_end": pd.Timestamp(dates[start - 1]).isoformat(),
                "test_start": pd.Timestamp(dates[start]).isoformat(),
                "test_end": pd.Timestamp(dates[min(count - 1, start + block - 1)]).isoformat(),
                "mae": float(mean_absolute_error(test["target"], predicted)),
                "n": int(len(test)),
            }
        )
    if not folds:
        return {"status": "skipped", "reason": "No rolling-origin fold had enough rows."}
    return {
        "status": "completed",
        "horizon_days": 1,
        "mae_mean": float(np.mean([fold["mae"] for fold in folds])),
        "folds": folds,
        "note": "Expanding-window evaluation. These folds were not used to choose hyperparameters.",
    }


def train_precipitation_model(
    observations: pd.DataFrame,
    *,
    algorithm: str = "auto",
    seed: int = 42,
    n_estimators: int = 300,
    min_train_rows: int = 80,
    horizons: tuple[int, ...] = (1, 2, 3),
    occurrence_mm: float = 0.1,
) -> dict:
    chosen = resolve_algorithm(algorithm)
    by_horizon = []
    models: dict[str, dict] = {}
    for horizon in horizons:
        supervised = build_supervised(observations, horizon, "precipitation_mm")
        supervised = supervised.dropna(subset=[*FEATURE_COLUMNS, "target"]).copy()
        supervised["occurred"] = (supervised["target"] > occurrence_mm).astype(int)
        dates = list(supervised["observed_at"].drop_duplicates())
        train_dates, val_dates, test_dates = chronological_split(dates)
        train = _slice(supervised, train_dates)
        validation = _slice(supervised, val_dates)
        test = _slice(supervised, test_dates)
        if len(train) < min_train_rows:
            raise ValueError(f"Precipitation horizon {horizon} has too few training rows.")
        positives = int(train["occurred"].sum())
        negatives = int(len(train) - positives)
        if positives == 0 or negatives == 0:
            raise ValueError(f"Precipitation horizon {horizon} training data has only one class.")
        scale = negatives / max(positives, 1)
        classifier = _classifier(chosen, n_estimators, seed, scale)
        classifier.fit(train[FEATURE_COLUMNS], train["occurred"])
        amount_model = _regressor(chosen, n_estimators, seed)
        amount_model.fit(train[FEATURE_COLUMNS], train["target"].clip(lower=0))
        val_proba = classifier.predict_proba(validation[FEATURE_COLUMNS])[:, 1]
        best_threshold = 0.5
        best_f1 = -1.0
        for threshold in np.linspace(0.1, 0.9, 17):
            score = f1_score(validation["occurred"], val_proba >= threshold, zero_division=0)
            if score > best_f1:
                best_f1 = float(score)
                best_threshold = float(threshold)
        test_proba = classifier.predict_proba(test[FEATURE_COLUMNS])[:, 1]
        test_hat = (test_proba >= best_threshold).astype(int)
        climatology_rate = float(train["occurred"].mean())
        climatology_proba = np.full(len(test), climatology_rate)
        persistence_hat = (test["precip_lag_1"] > occurrence_mm).astype(int)
        persistence_proba = persistence_hat.astype(float)
        amount_pred = np.clip(amount_model.predict(test[FEATURE_COLUMNS]), 0, None)
        wet = test["target"] > occurrence_mm
        mean_amount = float(train["target"].clip(lower=0).mean())

        def class_metrics(y_true, y_hat, proba) -> dict:
            return {
                "precision": float(precision_score(y_true, y_hat, zero_division=0)),
                "recall": float(recall_score(y_true, y_hat, zero_division=0)),
                "f1": float(f1_score(y_true, y_hat, zero_division=0)),
                "pr_auc": float(average_precision_score(y_true, proba)) if len(np.unique(y_true)) > 1 else None,
                "brier": float(brier_score_loss(y_true, proba)),
                "n": int(len(y_true)),
            }

        by_horizon.append(
            {
                "horizon_days": horizon,
                "occurrence_threshold_mm": occurrence_mm,
                "decision_threshold": best_threshold,
                "decision_threshold_source": "validation_max_f1",
                "positive_rate_train": climatology_rate,
                "positive_rate_test": float(test["occurred"].mean()),
                "test": class_metrics(test["occurred"], test_hat, test_proba),
                "validation": class_metrics(
                    validation["occurred"],
                    (val_proba >= best_threshold).astype(int),
                    val_proba,
                ),
                "climatology_baseline_test": class_metrics(
                    test["occurred"],
                    np.full(len(test), int(climatology_rate >= 0.5)),
                    climatology_proba,
                ),
                "persistence_baseline_test": class_metrics(test["occurred"], persistence_hat, persistence_proba),
                "amount_test": {
                    "mae_all": float(mean_absolute_error(test["target"], amount_pred)),
                    "mae_wet": float(mean_absolute_error(test.loc[wet, "target"], amount_pred[wet.to_numpy()]))
                    if wet.any()
                    else None,
                    "n_wet": int(wet.sum()),
                },
                "amount_persistence_mae_all": float(
                    mean_absolute_error(test["target"], test["precip_lag_1"].clip(lower=0))
                ),
                "amount_climatology_mae_all": float(
                    mean_absolute_error(test["target"], np.full(len(test), mean_amount))
                ),
                "split": {"train": _period(train), "validation": _period(validation), "test": _period(test)},
            }
        )
        models[str(horizon)] = {
            "classifier": classifier,
            "amount": amount_model,
            "decision_threshold": best_threshold,
            "occurrence_mm": occurrence_mm,
        }

    version = datetime.now(timezone.utc).strftime("pr-%Y%m%dT%H%M%SZ")
    return {
        "artifact": {
            "kind": "precipitation",
            "algorithm": chosen,
            "version": version,
            "seed": seed,
            "feature_columns": FEATURE_COLUMNS,
            "horizons": list(horizons),
            "models": models,
        },
        "report": {
            "name": "precipitation",
            "version": version,
            "algorithm": chosen,
            "target": "daily_precipitation_mm",
            "seed": seed,
            "by_horizon": by_horizon,
            "limitations": PRECIPITATION_LIMITATIONS,
            "validation_use": (
                "The occurrence threshold was selected on validation by maximum F1 and frozen before test scoring. "
                "Brier score and PR-AUC do not use that threshold."
            ),
            "trained_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def train_anomaly_model(observations: pd.DataFrame, *, seed: int = 42, contamination: float = 0.03) -> dict:
    columns = ["temperature_c", "precipitation_mm", "humidity_pct", "wind_speed_kmh", "pressure_hpa"]
    frame = observations.copy()
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    dates = sorted(frame["observed_at"].drop_duplicates())
    if len(dates) < 40:
        raise ValueError("Not enough daily history to fit an exploratory anomaly model.")
    cut = dates[int(len(dates) * 0.85)]
    train = frame[frame["observed_at"] < cut].dropna(subset=columns)
    models = {}
    medians = {}
    for location_id, group in train.groupby("location_id"):
        if len(group) < 40:
            continue
        matrix = group[columns]
        model = IsolationForest(
            n_estimators=200,
            contamination=contamination,
            random_state=seed,
        )
        model.fit(matrix)
        models[str(int(location_id))] = model
        medians[str(int(location_id))] = {column: float(matrix[column].median()) for column in columns}
    version = datetime.now(timezone.utc).strftime("an-%Y%m%dT%H%M%SZ")
    report = {
        "name": "anomaly",
        "version": version,
        "algorithm": "IsolationForest",
        "exploratory": True,
        "classification_metrics": None,
        "reason": "No labeled anomalies are available, so classification metrics are not computed.",
        "fit_locations": [int(key) for key in models],
        "train_end": pd.Timestamp(cut).isoformat(),
        "feature_columns": columns,
        "contamination": contamination,
        "seed": seed,
        "limitations": ANOMALY_LIMITATIONS,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    artifact = {
        "kind": "anomaly",
        "version": version,
        "feature_columns": columns,
        "models": models,
        "medians": medians,
        "contamination": contamination,
        "seed": seed,
        "train_end": pd.Timestamp(cut).isoformat(),
    }
    return {"artifact": artifact, "report": report}


def save_bundle(path, bundle: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)


def load_bundle(path):
    return joblib.load(path)
