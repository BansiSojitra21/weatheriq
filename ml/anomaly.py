from __future__ import annotations

import math

import numpy as np

MIN_REFERENCE = 14


def reference_bounds(history: list[float] | np.ndarray, threshold: float = 3.5) -> dict | None:
    """Robust center and range from earlier observations. The current point is not included."""
    values = np.asarray(history, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < MIN_REFERENCE:
        return None
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad >= 1e-6:
        scale = mad / 0.6745
        detail = "modified_z_mad"
    else:
        q1, q3 = np.percentile(values, [25, 75])
        iqr = float(q3 - q1)
        if iqr < 1e-6:
            return {
                "median": median,
                "mad": 0.0,
                "scale": 0.0,
                "low": median,
                "high": median,
                "n": int(len(values)),
                "detail": "no_variation",
            }
        scale = iqr / 1.349
        detail = "modified_z_iqr"
    return {
        "median": median,
        "mad": mad,
        "scale": float(scale),
        "low": median - threshold * scale,
        "high": median + threshold * scale,
        "n": int(len(values)),
        "detail": detail,
    }


def modified_z(value: float, bounds: dict) -> float:
    scale = float(bounds["scale"])
    median = float(bounds["median"])
    if scale == 0:
        return 0.0 if math.isclose(value, median) else math.inf
    return (value - median) / scale


def is_flagged(value: float, bounds: dict, threshold: float = 3.5) -> bool:
    if bounds.get("detail") == "no_variation":
        return not math.isclose(value, float(bounds["median"]))
    return abs(modified_z(value, bounds)) > threshold


def explain(variable: str, value: float, bounds: dict, score: float, threshold: float) -> str:
    labels = {
        "temperature_c": "Temperature",
        "precipitation_mm": "Rain",
        "humidity_pct": "Humidity",
        "wind_speed_kmh": "Wind",
        "pressure_hpa": "Pressure",
    }
    name = labels.get(variable, variable)
    return (
        f"{name} was {value:.2f}, outside the usual range "
        f"{bounds['low']:.2f} to {bounds['high']:.2f} "
        f"(typical value {bounds['median']:.2f}, unusualness score {score:.2f}, cutoff {threshold:.1f}). "
        f"The reference uses the previous {bounds['n']} finite observations and excludes this timestamp. "
        "This marks an unusual value relative to recent history. It is not a hazard warning."
    )
