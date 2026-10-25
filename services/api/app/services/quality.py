from __future__ import annotations

import math

RANGES: dict[str, tuple[float, float]] = {
    "temperature_c": (-80, 60),
    "temperature_min_c": (-80, 60),
    "temperature_max_c": (-80, 60),
    "apparent_temperature_c": (-90, 70),
    "humidity_pct": (0, 100),
    "precipitation_mm": (0, 2000),
    "precipitation_probability": (0, 100),
    "wind_speed_kmh": (0, 500),
    "wind_direction_deg": (0, 360),
    "pressure_hpa": (870, 1085),
    "cloud_cover_pct": (0, 100),
}


def clean_value(name: str, value: object) -> float | None:
    """Return a finite in-range float, or None when the provider value is missing or implausible."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    low, high = RANGES[name]
    if number < low or number > high:
        return None
    return number


def clean_code(value: object) -> int | None:
    if value is None:
        return None
    try:
        number = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 99:
        return None
    return number
