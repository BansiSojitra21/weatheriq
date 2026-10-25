from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.services.quality import clean_code, clean_value

logger = logging.getLogger(__name__)

DAILY_VARS = [
    "temperature_2m_mean",
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_mean",
    "precipitation_sum",
    "relative_humidity_2m_mean",
    "wind_speed_10m_max",
    "wind_direction_10m_dominant",
    "pressure_msl_mean",
    "cloud_cover_mean",
    "weather_code",
    "sunrise",
    "sunset",
]
HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "pressure_msl",
    "wind_speed_10m",
    "wind_direction_10m",
    "apparent_temperature",
]
FORECAST_HOURLY = [
    "temperature_2m",
    "precipitation_probability",
    "precipitation",
    "weather_code",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "cloud_cover",
    "apparent_temperature",
    "pressure_msl",
]
FORECAST_DAILY = [
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "sunrise",
    "sunset",
    "wind_speed_10m_max",
    "apparent_temperature_max",
]
PREVIOUS_HOURLY = [
    "temperature_2m_previous_day1",
    "temperature_2m_previous_day2",
    "temperature_2m_previous_day3",
    "temperature_2m_previous_day7",
    "precipitation_previous_day1",
    "precipitation_previous_day2",
    "precipitation_previous_day3",
    "precipitation_previous_day7",
]
RETRY_STATUSES = {429, 500, 502, 503, 504}


def parse_time(value: str | None) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value).replace("Z", "+00:00")
    if len(text) == 10:
        parsed = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
    return parsed


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return get_settings().resolved_cache_dir() / f"{digest}.json"


def _read_cache(url: str, ttl: timedelta) -> dict | None:
    path = _cache_path(url)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(payload["fetched_at"])
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None
    if datetime.now(timezone.utc) - fetched > ttl:
        return None
    logger.info("open_meteo_cache_hit url=%s", url.split("?", 1)[0])
    return payload["body"]


def _write_cache(url: str, body: dict) -> None:
    path = _cache_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "url": url, "body": body}),
        encoding="utf-8",
    )


def fetch_json(url: str, *, ttl: timedelta, client: httpx.Client | None = None) -> dict:
    cached = _read_cache(url, ttl)
    if cached is not None:
        return cached
    settings = get_settings()
    owns_client = client is None
    http = client or httpx.Client(timeout=settings.request_timeout_seconds)
    last_error: Exception | None = None
    try:
        for attempt in range(3):
            try:
                response = http.get(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                delay = min(8.0, 0.5 * (2**attempt))
                logger.warning("open_meteo_retry attempt=%s error=%s", attempt + 1, exc)
                time.sleep(delay)
                continue
            if response.status_code in RETRY_STATUSES:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = min(10.0, float(retry_after)) if retry_after else min(8.0, 0.5 * (2**attempt))
                except ValueError:
                    delay = min(8.0, 0.5 * (2**attempt))
                logger.warning("open_meteo_retry attempt=%s status=%s", attempt + 1, response.status_code)
                time.sleep(delay)
                last_error = httpx.HTTPStatusError(
                    f"HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
                continue
            response.raise_for_status()
            body = response.json()
            if body.get("error"):
                raise RuntimeError(body.get("reason") or "The weather service returned an error.")
            _write_cache(url, body)
            return body
    finally:
        if owns_client:
            http.close()
    raise RuntimeError(f"Weather data request failed after retries: {last_error}")


def _query(base: str, params: dict) -> str:
    clean = {key: value for key, value in params.items() if value is not None}
    return f"{base}?{urlencode(clean)}"


def _series(block: dict, key: str, index: int):
    values = block.get(key) or []
    if index >= len(values):
        return None
    return values[index]


def parse_daily_archive(payload: dict) -> list[dict]:
    daily = payload.get("daily") or {}
    rows = []
    for index, stamp in enumerate(daily.get("time") or []):
        observed = parse_time(stamp)
        if observed is None:
            continue
        rows.append(
            {
                "observed_at": observed,
                "temperature_c": clean_value("temperature_c", _series(daily, "temperature_2m_mean", index)),
                "temperature_min_c": clean_value("temperature_min_c", _series(daily, "temperature_2m_min", index)),
                "temperature_max_c": clean_value("temperature_max_c", _series(daily, "temperature_2m_max", index)),
                "apparent_temperature_c": clean_value(
                    "apparent_temperature_c", _series(daily, "apparent_temperature_mean", index)
                ),
                "humidity_pct": clean_value("humidity_pct", _series(daily, "relative_humidity_2m_mean", index)),
                "precipitation_mm": clean_value("precipitation_mm", _series(daily, "precipitation_sum", index)),
                "wind_speed_kmh": clean_value("wind_speed_kmh", _series(daily, "wind_speed_10m_max", index)),
                "wind_direction_deg": clean_value(
                    "wind_direction_deg", _series(daily, "wind_direction_10m_dominant", index)
                ),
                "pressure_hpa": clean_value("pressure_hpa", _series(daily, "pressure_msl_mean", index)),
                "cloud_cover_pct": clean_value("cloud_cover_pct", _series(daily, "cloud_cover_mean", index)),
                "weather_code": clean_code(_series(daily, "weather_code", index)),
                "sunrise_at": parse_time(_series(daily, "sunrise", index)),
                "sunset_at": parse_time(_series(daily, "sunset", index)),
            }
        )
    return rows


def parse_hourly_archive(payload: dict) -> list[dict]:
    hourly = payload.get("hourly") or {}
    rows = []
    for index, stamp in enumerate(hourly.get("time") or []):
        observed = parse_time(stamp)
        if observed is None:
            continue
        rows.append(
            {
                "observed_at": observed,
                "temperature_c": clean_value("temperature_c", _series(hourly, "temperature_2m", index)),
                "apparent_temperature_c": clean_value(
                    "apparent_temperature_c", _series(hourly, "apparent_temperature", index)
                ),
                "humidity_pct": clean_value("humidity_pct", _series(hourly, "relative_humidity_2m", index)),
                "precipitation_mm": clean_value("precipitation_mm", _series(hourly, "precipitation", index)),
                "wind_speed_kmh": clean_value("wind_speed_kmh", _series(hourly, "wind_speed_10m", index)),
                "wind_direction_deg": clean_value("wind_direction_deg", _series(hourly, "wind_direction_10m", index)),
                "pressure_hpa": clean_value("pressure_hpa", _series(hourly, "pressure_msl", index)),
                "cloud_cover_pct": clean_value("cloud_cover_pct", _series(hourly, "cloud_cover", index)),
                "weather_code": clean_code(_series(hourly, "weather_code", index)),
            }
        )
    return rows


def parse_current(payload: dict) -> dict | None:
    current = payload.get("current") or {}
    observed = parse_time(current.get("time"))
    if observed is None:
        return None
    return {
        "observed_at": observed,
        "temperature_c": clean_value("temperature_c", current.get("temperature_2m")),
        "apparent_temperature_c": clean_value("apparent_temperature_c", current.get("apparent_temperature")),
        "humidity_pct": clean_value("humidity_pct", current.get("relative_humidity_2m")),
        "precipitation_mm": clean_value("precipitation_mm", current.get("precipitation")),
        "wind_speed_kmh": clean_value("wind_speed_kmh", current.get("wind_speed_10m")),
        "wind_direction_deg": clean_value("wind_direction_deg", current.get("wind_direction_10m")),
        "pressure_hpa": clean_value("pressure_hpa", current.get("pressure_msl")),
        "cloud_cover_pct": clean_value("cloud_cover_pct", current.get("cloud_cover")),
        "weather_code": clean_code(current.get("weather_code")),
    }


def parse_forecast_hourly(payload: dict) -> list[dict]:
    hourly = payload.get("hourly") or {}
    rows = []
    for index, stamp in enumerate(hourly.get("time") or []):
        valid = parse_time(stamp)
        if valid is None:
            continue
        rows.append(
            {
                "valid_at": valid,
                "granularity": "hourly",
                "temperature_c": clean_value("temperature_c", _series(hourly, "temperature_2m", index)),
                "apparent_temperature_c": clean_value(
                    "apparent_temperature_c", _series(hourly, "apparent_temperature", index)
                ),
                "humidity_pct": clean_value("humidity_pct", _series(hourly, "relative_humidity_2m", index)),
                "precipitation_mm": clean_value("precipitation_mm", _series(hourly, "precipitation", index)),
                "precipitation_probability": clean_value(
                    "precipitation_probability", _series(hourly, "precipitation_probability", index)
                ),
                "wind_speed_kmh": clean_value("wind_speed_kmh", _series(hourly, "wind_speed_10m", index)),
                "wind_direction_deg": clean_value("wind_direction_deg", _series(hourly, "wind_direction_10m", index)),
                "pressure_hpa": clean_value("pressure_hpa", _series(hourly, "pressure_msl", index)),
                "cloud_cover_pct": clean_value("cloud_cover_pct", _series(hourly, "cloud_cover", index)),
                "weather_code": clean_code(_series(hourly, "weather_code", index)),
            }
        )
    return rows


def parse_forecast_daily(payload: dict) -> list[dict]:
    daily = payload.get("daily") or {}
    rows = []
    for index, stamp in enumerate(daily.get("time") or []):
        valid = parse_time(stamp)
        if valid is None:
            continue
        rows.append(
            {
                "valid_at": valid,
                "granularity": "daily",
                "temperature_min_c": clean_value("temperature_min_c", _series(daily, "temperature_2m_min", index)),
                "temperature_max_c": clean_value("temperature_max_c", _series(daily, "temperature_2m_max", index)),
                "apparent_temperature_c": clean_value(
                    "apparent_temperature_c", _series(daily, "apparent_temperature_max", index)
                ),
                "precipitation_mm": clean_value("precipitation_mm", _series(daily, "precipitation_sum", index)),
                "precipitation_probability": clean_value(
                    "precipitation_probability", _series(daily, "precipitation_probability_max", index)
                ),
                "wind_speed_kmh": clean_value("wind_speed_kmh", _series(daily, "wind_speed_10m_max", index)),
                "weather_code": clean_code(_series(daily, "weather_code", index)),
                "sunrise_at": parse_time(_series(daily, "sunrise", index)),
                "sunset_at": parse_time(_series(daily, "sunset", index)),
            }
        )
    return rows


def aggregate_previous_runs(payload: dict) -> dict[int, list[dict]]:
    """Aggregate hourly previous-run fields into daily means and precipitation sums.

    previous_dayN is the value that the numerical forecast issued about N days earlier
    assigned to that hour. Daily temperature is the mean of the available hours.
    """
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    leads = {1: [], 2: [], 3: [], 7: []}
    buckets: dict[tuple[int, datetime], dict] = {}
    for index, stamp in enumerate(times):
        valid = parse_time(stamp)
        if valid is None:
            continue
        day = valid.replace(hour=0, minute=0, second=0, microsecond=0)
        for lead in leads:
            temp = clean_value("temperature_c", _series(hourly, f"temperature_2m_previous_day{lead}", index))
            precip = clean_value("precipitation_mm", _series(hourly, f"precipitation_previous_day{lead}", index))
            slot = buckets.setdefault((lead, day), {"temps": [], "precips": []})
            if temp is not None:
                slot["temps"].append(temp)
            if precip is not None:
                slot["precips"].append(precip)
    grouped: dict[int, list[dict]] = {1: [], 2: [], 3: [], 7: []}
    for (lead, day), slot in sorted(buckets.items()):
        if not slot["temps"] and not slot["precips"]:
            continue
        grouped[lead].append(
            {
                "valid_at": day,
                "issued_at": day - timedelta(days=lead),
                "granularity": "daily",
                "lead_days": lead,
                "temperature_c": round(sum(slot["temps"]) / len(slot["temps"]), 3) if slot["temps"] else None,
                "precipitation_mm": round(sum(slot["precips"]), 3) if slot["precips"] else None,
            }
        )
    return grouped


def archive_daily_url(latitude: float, longitude: float, start: str, end: str) -> str:
    return _query(
        get_settings().archive_url,
        {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start,
            "end_date": end,
            "daily": ",".join(DAILY_VARS),
            "timezone": "UTC",
        },
    )


def archive_hourly_url(latitude: float, longitude: float, start: str, end: str) -> str:
    return _query(
        get_settings().archive_url,
        {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start,
            "end_date": end,
            "hourly": ",".join(HOURLY_VARS),
            "timezone": "UTC",
        },
    )


def forecast_url(latitude: float, longitude: float) -> str:
    return _query(
        get_settings().forecast_url,
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "apparent_temperature",
                    "precipitation",
                    "weather_code",
                    "cloud_cover",
                    "pressure_msl",
                    "wind_speed_10m",
                    "wind_direction_10m",
                ]
            ),
            "hourly": ",".join(FORECAST_HOURLY),
            "daily": ",".join(FORECAST_DAILY),
            "forecast_days": 7,
            "past_days": 0,
            "timezone": "UTC",
        },
    )


def previous_runs_url(latitude: float, longitude: float, past_days: int) -> str:
    return _query(
        get_settings().previous_runs_url,
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(PREVIOUS_HOURLY),
            "past_days": past_days,
            "forecast_days": 1,
            "timezone": "UTC",
        },
    )


def geocode_url(name: str) -> str:
    return _query(
        get_settings().geocoding_url,
        {"name": name, "count": 5, "language": "en", "format": "json"},
    )
