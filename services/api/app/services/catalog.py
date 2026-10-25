from __future__ import annotations

import math
from datetime import datetime, timezone

DISCLAIMER = (
    "WeatherIQ is an analytical dashboard. It is not a replacement for official "
    "emergency alerts or professional meteorological forecasts."
)
ATTRIBUTION = "Weather data by Open-Meteo.com, licensed under CC BY 4.0."
SOURCE_NOTE = "Current conditions and forecasts come from published weather data, not a sensor at this location."
TEMPERATURE_NOTE = (
    "This temperature prediction uses recent daily weather for this city. "
    "It is checked against past days and is not an official forecast. "
    "The likely range is an estimate, not a guarantee."
)
PRECIPITATION_NOTE = (
    "Rain predictions use recent daily totals. A day counts as wet above 0.1 mm. "
    "This is not a flood warning."
)
ANOMALY_NOTE = (
    "A flag means the measurement looks unusual compared with recent days. "
    "It does not mean the weather is dangerous."
)

WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

UNIT_LABELS = {
    "metric": {"temperature": "°C", "precipitation": "mm", "wind": "km/h", "pressure": "hPa"},
    "imperial": {"temperature": "°F", "precipitation": "in", "wind": "mph", "pressure": "inHg"},
}


def condition_label(code: int | None) -> str | None:
    if code is None:
        return None
    return WMO_CODES.get(int(code), f"Weather code {int(code)}")


def compass(degrees: float | None) -> str | None:
    if degrees is None or not math.isfinite(degrees):
        return None
    index = int((float(degrees) % 360) / 22.5 + 0.5) % 16
    return COMPASS[index]


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return as_utc(value).isoformat().replace("+00:00", "Z")


def convert_temperature(value: float | None, units: str) -> float | None:
    if value is None:
        return None
    converted = value * 9 / 5 + 32 if units == "imperial" else value
    return round(converted, 2)


def convert_precipitation(value: float | None, units: str) -> float | None:
    if value is None:
        return None
    converted = value / 25.4 if units == "imperial" else value
    return round(converted, 3 if units == "imperial" else 2)


def convert_wind(value: float | None, units: str) -> float | None:
    if value is None:
        return None
    converted = value * 0.621371 if units == "imperial" else value
    return round(converted, 2)


def convert_pressure(value: float | None, units: str) -> float | None:
    if value is None:
        return None
    converted = value * 0.02953 if units == "imperial" else value
    return round(converted, 2)


def round_or_none(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)
