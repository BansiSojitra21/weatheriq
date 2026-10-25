from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ml.features import FEATURE_COLUMNS, build_supervised
from ml.splits import chronological_split
from ml.train import load_bundle, save_bundle, train_precipitation_model, train_temperature_model


def _frame(days: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for location_id, latitude in ((1, 19.0), (2, 40.7)):
        for offset in range(days):
            moment = start + timedelta(days=offset)
            doy = moment.timetuple().tm_yday
            temperature = 18 + 8 * np.sin(2 * np.pi * doy / 365.25) + float(rng.normal(0, 0.8))
            wet = float(rng.random() < 0.25)
            rows.append(
                {
                    "location_id": location_id,
                    "latitude": latitude,
                    "observed_at": moment,
                    "temperature_c": temperature,
                    "precipitation_mm": wet * float(rng.gamma(1.4, 2)),
                    "humidity_pct": 60 + float(rng.normal(0, 5)),
                    "wind_speed_kmh": 12 + float(rng.normal(0, 2)),
                    "pressure_hpa": 1013 + float(rng.normal(0, 3)),
                    "cloud_cover_pct": 40 + float(rng.normal(0, 8)),
                }
            )
    return pd.DataFrame(rows)


def test_features_do_not_use_future_weather():
    frame = _frame(80)
    original = build_supervised(frame, 1, "temperature_c")
    cutoff = pd.Timestamp("2024-02-15", tz="UTC")
    corrupted = frame.copy()
    corrupted.loc[corrupted["observed_at"] > cutoff, "temperature_c"] = 80
    changed = build_supervised(corrupted, 1, "temperature_c")
    before = original[original["observed_at"] <= cutoff].set_index(["location_id", "observed_at"])
    after = changed[changed["observed_at"] <= cutoff].set_index(["location_id", "observed_at"])
    pd.testing.assert_frame_equal(before[FEATURE_COLUMNS], after[FEATURE_COLUMNS])
    assert "target" not in FEATURE_COLUMNS
    assert not before["target"].equals(after["target"])


def test_chronological_split_orders_periods():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    dates = [start + timedelta(days=offset) for offset in range(90)]
    train, validation, test = chronological_split(dates)
    assert max(train) < min(validation) < max(validation) < min(test)


def test_temperature_model_holdout_and_reload(tmp_path):
    frame = _frame(100)
    trained = train_temperature_model(
        frame,
        algorithm="sklearn",
        n_estimators=25,
        min_train_rows=40,
        compute_shap=False,
        horizons=(1,),
    )
    report = trained["report"]
    horizon = report["by_horizon"][0]
    assert horizon["split"]["train"]["end"] < horizon["split"]["validation"]["start"]
    assert horizon["split"]["validation"]["end"] < horizon["split"]["test"]["start"]
    assert horizon["test"]["n"] > 0
    assert "training" not in horizon["test"]
    path = tmp_path / "temperature.joblib"
    save_bundle(path, trained["artifact"])
    loaded = load_bundle(path)
    assert loaded["feature_columns"] == FEATURE_COLUMNS
    model = loaded["models"]["1"]["point"]
    sample = frame.head(20).copy()
    supervised = build_supervised(sample, 1, "temperature_c").dropna(subset=FEATURE_COLUMNS)
    prediction = float(model.predict(supervised[FEATURE_COLUMNS].head(1))[0])
    assert np.isfinite(prediction)


def test_precipitation_holdout_metrics_are_present():
    trained = train_precipitation_model(
        _frame(100),
        algorithm="sklearn",
        n_estimators=25,
        min_train_rows=40,
        horizons=(1,),
    )
    metrics = trained["report"]["by_horizon"][0]["test"]
    for key in ("precision", "recall", "f1", "pr_auc", "brier", "n"):
        assert key in metrics
    assert trained["report"]["by_horizon"][0]["decision_threshold_source"] == "validation_max_f1"
