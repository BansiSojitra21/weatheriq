from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.orm import Session

from app.db.models import WeatherObservation
from app.services.catalog import (
    UNIT_LABELS,
    as_utc,
    convert_precipitation,
    convert_pressure,
    convert_temperature,
    convert_wind,
    isoformat,
)

COLUMNS = [
    "temperature_c",
    "temperature_min_c",
    "temperature_max_c",
    "humidity_pct",
    "precipitation_mm",
    "wind_speed_kmh",
    "pressure_hpa",
    "cloud_cover_pct",
]
SEASONS = {
    12: "DJF",
    1: "DJF",
    2: "DJF",
    3: "MAM",
    4: "MAM",
    5: "MAM",
    6: "JJA",
    7: "JJA",
    8: "JJA",
    9: "SON",
    10: "SON",
    11: "SON",
}


def observation_frame(
    session: Session,
    location_id: int,
    start: datetime,
    end: datetime,
    granularity: str = "daily",
) -> pd.DataFrame:
    rows = (
        session.query(WeatherObservation)
        .filter(
            WeatherObservation.location_id == location_id,
            WeatherObservation.granularity == granularity,
            WeatherObservation.observed_at >= start,
            WeatherObservation.observed_at <= end,
        )
        .order_by(WeatherObservation.observed_at.asc())
        .all()
    )
    records = []
    for row in rows:
        records.append(
            {
                "observed_at": as_utc(row.observed_at),
                "provider": row.provider,
                "retrieved_at": as_utc(row.retrieved_at),
                **{column: getattr(row, column) for column in COLUMNS},
            }
        )
    frame = pd.DataFrame(records)
    if frame.empty:
        frame = pd.DataFrame(columns=["observed_at", "provider", "retrieved_at", *COLUMNS])
    else:
        frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    return frame


def _present_row(row: pd.Series, units: str) -> dict:
    return {
        "observed_at": isoformat(row["observed_at"].to_pydatetime()),
        "temperature": convert_temperature(None if pd.isna(row["temperature_c"]) else row["temperature_c"], units),
        "temperature_min": convert_temperature(
            None if pd.isna(row["temperature_min_c"]) else row["temperature_min_c"], units
        ),
        "temperature_max": convert_temperature(
            None if pd.isna(row["temperature_max_c"]) else row["temperature_max_c"], units
        ),
        "humidity": None if pd.isna(row["humidity_pct"]) else round(float(row["humidity_pct"]), 2),
        "precipitation": convert_precipitation(
            None if pd.isna(row["precipitation_mm"]) else row["precipitation_mm"], units
        ),
        "wind_speed": convert_wind(None if pd.isna(row["wind_speed_kmh"]) else row["wind_speed_kmh"], units),
        "pressure": convert_pressure(None if pd.isna(row["pressure_hpa"]) else row["pressure_hpa"], units),
        "cloud_cover": None if pd.isna(row["cloud_cover_pct"]) else round(float(row["cloud_cover_pct"]), 2),
    }


def missing_stats(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {column: {"count": 0, "missing": 0, "missing_rate": None} for column in COLUMNS}
    stats = {}
    total = len(frame)
    for column in COLUMNS:
        missing = int(frame[column].isna().sum())
        stats[column] = {"count": total - missing, "missing": missing, "missing_rate": round(missing / total, 4)}
    return stats


def summary(frame: pd.DataFrame, units: str) -> dict:
    stats = {}
    converters = {
        "temperature_c": lambda value: convert_temperature(value, units),
        "temperature_min_c": lambda value: convert_temperature(value, units),
        "temperature_max_c": lambda value: convert_temperature(value, units),
        "precipitation_mm": lambda value: convert_precipitation(value, units),
        "wind_speed_kmh": lambda value: convert_wind(value, units),
        "pressure_hpa": lambda value: convert_pressure(value, units),
        "humidity_pct": lambda value: round(float(value), 2),
        "cloud_cover_pct": lambda value: round(float(value), 2),
    }
    for column in COLUMNS:
        series = frame[column].dropna() if not frame.empty else pd.Series(dtype=float)
        if series.empty:
            stats[column] = {"count": 0, "mean": None, "min": None, "max": None}
            continue
        convert = converters[column]
        stats[column] = {
            "count": int(series.shape[0]),
            "mean": convert(float(series.mean())),
            "min": convert(float(series.min())),
            "max": convert(float(series.max())),
        }
    return {
        "rows": int(len(frame)),
        "variables": stats,
        "missing": missing_stats(frame),
        "units": units,
        "unit_labels": UNIT_LABELS[units],
    }


def series(frame: pd.DataFrame, units: str, variable: str) -> list[dict]:
    column = {
        "temperature": "temperature_c",
        "precipitation": "precipitation_mm",
        "humidity": "humidity_pct",
        "wind_speed": "wind_speed_kmh",
        "pressure": "pressure_hpa",
        "cloud_cover": "cloud_cover_pct",
    }.get(variable, "temperature_c")
    convert = {
        "temperature_c": lambda value: convert_temperature(value, units),
        "precipitation_mm": lambda value: convert_precipitation(value, units),
        "wind_speed_kmh": lambda value: convert_wind(value, units),
        "pressure_hpa": lambda value: convert_pressure(value, units),
    }.get(column, lambda value: round(float(value), 2))
    points = []
    rolling = frame[column].rolling(7, min_periods=3).mean() if not frame.empty else []
    for index, row in frame.iterrows():
        raw = row[column]
        value = None if pd.isna(raw) else convert(float(raw))
        roll_raw = rolling.loc[index]
        points.append(
            {
                "observed_at": isoformat(row["observed_at"].to_pydatetime()),
                "value": value,
                "rolling_mean": None if pd.isna(roll_raw) else convert(float(roll_raw)),
            }
        )
    return points


def monthly(frame: pd.DataFrame, units: str) -> list[dict]:
    if frame.empty:
        return []
    work = frame.copy()
    work["month"] = work["observed_at"].dt.month
    grouped = work.groupby("month", sort=True)
    rows = []
    for month, group in grouped:
        temp = group["temperature_c"].dropna()
        precip = group["precipitation_mm"].dropna()
        rows.append(
            {
                "month": int(month),
                "temperature_mean": convert_temperature(float(temp.mean()), units) if not temp.empty else None,
                "precipitation_total": convert_precipitation(float(precip.sum()), units) if not precip.empty else None,
                "observations": int(len(group)),
            }
        )
    return rows


def seasonal(frame: pd.DataFrame, units: str) -> list[dict]:
    if frame.empty:
        return []
    work = frame.copy()
    work["season"] = work["observed_at"].dt.month.map(SEASONS)
    rows = []
    for season, group in work.groupby("season", sort=False):
        temp = group["temperature_c"].dropna()
        precip = group["precipitation_mm"].dropna()
        rows.append(
            {
                "season": season,
                "temperature_mean": convert_temperature(float(temp.mean()), units) if not temp.empty else None,
                "precipitation_total": convert_precipitation(float(precip.sum()), units) if not precip.empty else None,
                "observations": int(len(group)),
            }
        )
    return rows


def correlation(frame: pd.DataFrame) -> dict:
    columns = ["temperature_c", "precipitation_mm", "humidity_pct", "wind_speed_kmh", "pressure_hpa", "cloud_cover_pct"]
    if frame.empty:
        return {"variables": columns, "matrix": [], "counts": [], "note": "No observations in the selected range."}
    matrix = []
    counts = []
    for left in columns:
        row = []
        count_row = []
        for right in columns:
            pair = frame[[left, right]].dropna()
            count_row.append(int(len(pair)))
            if left == right:
                row.append(1.0 if len(pair) >= 10 else None)
                continue
            if len(pair) < 10 or int(pair[left].nunique()) < 2 or int(pair[right].nunique()) < 2:
                row.append(None)
                continue
            row.append(round(float(pair[left].corr(pair[right])), 4))
        matrix.append(row)
        counts.append(count_row)
    return {
        "variables": columns,
        "matrix": matrix,
        "counts": counts,
        "note": "Pearson correlation on pairwise complete observations. Correlation does not depend on unit scaling.",
    }


def history_payload(
    frame: pd.DataFrame, units: str, location_id: int, start: datetime, end: datetime, granularity: str
) -> dict:
    return {
        "location_id": location_id,
        "granularity": granularity,
        "start": isoformat(start),
        "end": isoformat(end),
        "units": units,
        "unit_labels": UNIT_LABELS[units],
        "kind": "observation",
        "source": "open-meteo-archive",
        "series": [_present_row(row, units) for _, row in frame.iterrows()],
        "missing": missing_stats(frame),
    }


def to_csv(frame: pd.DataFrame, units: str) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "observed_at_utc",
            "kind",
            "provider",
            f"temperature_{units}",
            f"temperature_min_{units}",
            f"temperature_max_{units}",
            "humidity_pct",
            f"precipitation_{units}",
            f"wind_speed_{units}",
            f"pressure_{units}",
            "cloud_cover_pct",
        ]
    )
    for _, row in frame.iterrows():
        presented = _present_row(row, units)
        writer.writerow(
            [
                presented["observed_at"],
                "observation",
                row["provider"],
                presented["temperature"],
                presented["temperature_min"],
                presented["temperature_max"],
                presented["humidity"],
                presented["precipitation"],
                presented["wind_speed"],
                presented["pressure"],
                presented["cloud_cover"],
            ]
        )
    return buffer.getvalue()


def parse_bounds(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end < start:
        raise ValueError("end must be on or after start")
    return start, end
