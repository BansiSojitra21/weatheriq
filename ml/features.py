from __future__ import annotations

import numpy as np
import pandas as pd

# Weather lags and rolling statistics use only the issuance day and earlier days.
# Calendar fields use the target date because that calendar is known when the forecast is issued.
FEATURE_COLUMNS = [
    "temp_lag_1",
    "temp_lag_2",
    "temp_lag_3",
    "temp_lag_7",
    "temp_lag_14",
    "temp_roll_mean_7",
    "temp_roll_mean_14",
    "temp_roll_std_7",
    "precip_lag_1",
    "precip_lag_2",
    "precip_lag_7",
    "precip_roll_sum_7",
    "humidity_lag_1",
    "humidity_roll_mean_7",
    "wind_lag_1",
    "pressure_lag_1",
    "cloud_lag_1",
    "sin_doy",
    "cos_doy",
    "sin_doy2",
    "cos_doy2",
    "sin_dow",
    "cos_dow",
    "month",
    "latitude",
]


def _calendar(frame: pd.DataFrame) -> pd.DataFrame:
    doy = frame["target_time"].dt.dayofyear.to_numpy(dtype=float)
    dow = frame["target_time"].dt.dayofweek.to_numpy(dtype=float)
    frame["sin_doy"] = np.sin(2 * np.pi * doy / 365.25)
    frame["cos_doy"] = np.cos(2 * np.pi * doy / 365.25)
    frame["sin_doy2"] = np.sin(4 * np.pi * doy / 365.25)
    frame["cos_doy2"] = np.cos(4 * np.pi * doy / 365.25)
    frame["sin_dow"] = np.sin(2 * np.pi * dow / 7)
    frame["cos_dow"] = np.cos(2 * np.pi * dow / 7)
    frame["month"] = frame["target_time"].dt.month.astype(float)
    return frame


def build_supervised(observations: pd.DataFrame, horizon: int, target_column: str) -> pd.DataFrame:
    """Build one row per location and issuance day for a fixed lead time.

    The target is the weather value `horizon` days after the issuance day.
    Feature weather values never come from after the issuance day.
    """
    if horizon < 1:
        raise ValueError("horizon must be at least 1 day")
    required = {
        "location_id",
        "observed_at",
        "temperature_c",
        "precipitation_mm",
        "humidity_pct",
        "wind_speed_kmh",
        "pressure_hpa",
        "cloud_cover_pct",
        "latitude",
        target_column,
    }
    missing = required.difference(observations.columns)
    if missing:
        raise ValueError(f"Observations are missing columns: {sorted(missing)}")

    frame = observations.copy()
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    parts: list[pd.DataFrame] = []
    for _, group in frame.groupby("location_id", sort=False):
        group = group.sort_values("observed_at").copy()
        temperature = group["temperature_c"]
        precipitation = group["precipitation_mm"]
        humidity = group["humidity_pct"]
        group["temp_lag_1"] = temperature
        group["temp_lag_2"] = temperature.shift(1)
        group["temp_lag_3"] = temperature.shift(2)
        group["temp_lag_7"] = temperature.shift(6)
        group["temp_lag_14"] = temperature.shift(13)
        group["temp_roll_mean_7"] = temperature.rolling(7, min_periods=7).mean()
        group["temp_roll_mean_14"] = temperature.rolling(14, min_periods=14).mean()
        group["temp_roll_std_7"] = temperature.rolling(7, min_periods=7).std()
        group["precip_lag_1"] = precipitation
        group["precip_lag_2"] = precipitation.shift(1)
        group["precip_lag_7"] = precipitation.shift(6)
        group["precip_roll_sum_7"] = precipitation.rolling(7, min_periods=7).sum()
        group["humidity_lag_1"] = humidity
        group["humidity_roll_mean_7"] = humidity.rolling(7, min_periods=7).mean()
        group["wind_lag_1"] = group["wind_speed_kmh"]
        group["pressure_lag_1"] = group["pressure_hpa"]
        group["cloud_lag_1"] = group["cloud_cover_pct"]
        group["target"] = group[target_column].shift(-horizon)
        group["target_time"] = group["observed_at"] + pd.to_timedelta(horizon, unit="D")
        group = _calendar(group)
        group["horizon_days"] = horizon
        parts.append(group)
    if not parts:
        return pd.DataFrame(columns=[*FEATURE_COLUMNS, "target", "target_time", "location_id", "observed_at"])
    return pd.concat(parts, ignore_index=True)
