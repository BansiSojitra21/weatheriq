from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import CurrentCondition, ForecastRun, ForecastValue, IngestionRun, Location, WeatherObservation
from app.services.catalog import as_utc
from app.services.open_meteo import (
    aggregate_previous_runs,
    archive_daily_url,
    archive_hourly_url,
    fetch_json,
    forecast_url,
    parse_current,
    parse_daily_archive,
    parse_forecast_daily,
    parse_forecast_hourly,
    parse_hourly_archive,
    previous_runs_url,
)

logger = logging.getLogger(__name__)

OBSERVATION_FIELDS = [
    "temperature_c",
    "temperature_min_c",
    "temperature_max_c",
    "apparent_temperature_c",
    "humidity_pct",
    "precipitation_mm",
    "wind_speed_kmh",
    "wind_direction_deg",
    "pressure_hpa",
    "cloud_cover_pct",
    "weather_code",
    "sunrise_at",
    "sunset_at",
]


def _finish(run: IngestionRun, status: str, records: int, error: str | None = None) -> None:
    run.status = status
    run.records_written = records
    run.error = error
    run.finished_at = datetime.now(timezone.utc)


def upsert_observations(
    session: Session,
    location_id: int,
    granularity: str,
    rows: list[dict],
    retrieved_at: datetime,
    provider: str = "open-meteo",
) -> int:
    existing = {
        as_utc(row.observed_at): row
        for row in session.query(WeatherObservation).filter_by(location_id=location_id, granularity=granularity).all()
    }
    written = 0
    for row in rows:
        observed = as_utc(row["observed_at"])
        current = existing.get(observed)
        if current is None:
            current = WeatherObservation(
                location_id=location_id,
                observed_at=observed,
                granularity=granularity,
                provider=provider,
                retrieved_at=retrieved_at,
            )
            session.add(current)
            existing[observed] = current
        for field in OBSERVATION_FIELDS:
            if field in row:
                setattr(current, field, row.get(field))
        current.provider = provider
        current.retrieved_at = retrieved_at
        written += 1
    session.flush()
    return written


def upsert_current(session: Session, location_id: int, row: dict, retrieved_at: datetime) -> int:
    observed = as_utc(row["observed_at"])
    current = session.query(CurrentCondition).filter_by(location_id=location_id, observed_at=observed).one_or_none()
    if current is None:
        current = CurrentCondition(location_id=location_id, observed_at=observed, provider="open-meteo")
        session.add(current)
    for field in (
        "temperature_c",
        "apparent_temperature_c",
        "humidity_pct",
        "precipitation_mm",
        "wind_speed_kmh",
        "wind_direction_deg",
        "pressure_hpa",
        "cloud_cover_pct",
        "weather_code",
    ):
        setattr(current, field, row.get(field))
    current.retrieved_at = retrieved_at
    session.flush()
    return 1


def replace_forecast_run(
    session: Session,
    location: Location,
    model_name: str,
    issued_at: datetime,
    retrieved_at: datetime,
    values: list[dict],
    issuance_basis: str,
) -> int:
    run = (
        session.query(ForecastRun)
        .filter_by(location_id=location.id, provider="open-meteo", model_name=model_name)
        .one_or_none()
    )
    if run is None:
        run = ForecastRun(
            location_id=location.id,
            provider="open-meteo",
            model_name=model_name,
            issued_at=issued_at,
            retrieved_at=retrieved_at,
            issuance_basis=issuance_basis,
        )
        session.add(run)
        session.flush()
    else:
        run.issued_at = issued_at
        run.retrieved_at = retrieved_at
        run.issuance_basis = issuance_basis
        session.query(ForecastValue).filter_by(run_id=run.id).delete(synchronize_session=False)
        session.flush()
    for row in values:
        session.add(
            ForecastValue(
                run_id=run.id,
                valid_at=as_utc(row["valid_at"]),
                issued_at=as_utc(row["issued_at"]) if row.get("issued_at") else issued_at,
                granularity=row["granularity"],
                lead_days=row.get("lead_days"),
                temperature_c=row.get("temperature_c"),
                temperature_min_c=row.get("temperature_min_c"),
                temperature_max_c=row.get("temperature_max_c"),
                apparent_temperature_c=row.get("apparent_temperature_c"),
                humidity_pct=row.get("humidity_pct"),
                precipitation_mm=row.get("precipitation_mm"),
                precipitation_probability=row.get("precipitation_probability"),
                wind_speed_kmh=row.get("wind_speed_kmh"),
                wind_direction_deg=row.get("wind_direction_deg"),
                pressure_hpa=row.get("pressure_hpa"),
                cloud_cover_pct=row.get("cloud_cover_pct"),
                weather_code=row.get("weather_code"),
                sunrise_at=row.get("sunrise_at"),
                sunset_at=row.get("sunset_at"),
            )
        )
    session.flush()
    return len(values)


def _run(session: Session, location_id: int | None, kind: str) -> IngestionRun:
    record = IngestionRun(location_id=location_id, kind=kind, provider="open-meteo", status="running")
    session.add(record)
    session.flush()
    return record


def ingest_location(
    session: Session,
    location: Location,
    *,
    kinds: set[str] | None = None,
    history_days: int | None = None,
    hourly_days: int | None = None,
    previous_days: int | None = None,
) -> dict:
    settings = get_settings()
    selected = kinds or {"history", "hourly", "current", "forecast", "previous_runs"}
    history_days = history_days or settings.history_days
    hourly_days = hourly_days or settings.hourly_days
    previous_days = previous_days or settings.previous_run_days
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    summary = {"location_id": location.id, "records": 0, "kinds": {}}
    retrieved_at = datetime.now(timezone.utc)

    if "history" in selected:
        record = _run(session, location.id, "history")
        try:
            start = yesterday - timedelta(days=history_days - 1)
            payload = fetch_json(
                archive_daily_url(location.latitude, location.longitude, start.isoformat(), yesterday.isoformat()),
                ttl=timedelta(hours=settings.archive_cache_ttl_hours),
            )
            if payload.get("elevation") is not None and location.elevation_m is None:
                location.elevation_m = float(payload["elevation"])
            rows = parse_daily_archive(payload)
            count = upsert_observations(session, location.id, "daily", rows, retrieved_at)
            _finish(record, "succeeded", count)
            summary["kinds"]["history"] = count
            summary["records"] += count
            logger.info("ingested_daily_history location_id=%s records=%s", location.id, count)
        except Exception as exc:
            _finish(record, "failed", 0, str(exc))
            summary["kinds"]["history"] = {"error": str(exc)}
            logger.exception("history_ingestion_failed location_id=%s", location.id)

    if "hourly" in selected:
        record = _run(session, location.id, "hourly")
        try:
            start = yesterday - timedelta(days=hourly_days - 1)
            payload = fetch_json(
                archive_hourly_url(location.latitude, location.longitude, start.isoformat(), yesterday.isoformat()),
                ttl=timedelta(hours=settings.archive_cache_ttl_hours),
            )
            rows = parse_hourly_archive(payload)
            count = upsert_observations(session, location.id, "hourly", rows, retrieved_at)
            _finish(record, "succeeded", count)
            summary["kinds"]["hourly"] = count
            summary["records"] += count
        except Exception as exc:
            _finish(record, "failed", 0, str(exc))
            summary["kinds"]["hourly"] = {"error": str(exc)}
            logger.exception("hourly_ingestion_failed location_id=%s", location.id)

    if "current" in selected or "forecast" in selected:
        record = _run(session, location.id, "forecast")
        try:
            payload = fetch_json(
                forecast_url(location.latitude, location.longitude),
                ttl=timedelta(minutes=settings.cache_ttl_minutes),
            )
            count = 0
            if "current" in selected:
                current = parse_current(payload)
                if current is None:
                    raise RuntimeError("Current conditions were not returned.")
                count += upsert_current(session, location.id, current, retrieved_at)
            if "forecast" in selected:
                hourly = parse_forecast_hourly(payload)
                daily = parse_forecast_daily(payload)
                for row in hourly:
                    row["issued_at"] = retrieved_at
                    row["lead_days"] = None
                for row in daily:
                    row["issued_at"] = retrieved_at
                    row["lead_days"] = max(0, (row["valid_at"].date() - retrieved_at.date()).days)
                count += replace_forecast_run(
                    session,
                    location,
                    "forecast-hourly",
                    retrieved_at,
                    retrieved_at,
                    hourly,
                    "retrieval_time",
                )
                count += replace_forecast_run(
                    session,
                    location,
                    "forecast-daily",
                    retrieved_at,
                    retrieved_at,
                    daily,
                    "retrieval_time",
                )
            _finish(record, "succeeded", count)
            summary["kinds"]["forecast"] = count
            summary["records"] += count
        except Exception as exc:
            _finish(record, "failed", 0, str(exc))
            summary["kinds"]["forecast"] = {"error": str(exc)}
            logger.exception("forecast_ingestion_failed location_id=%s", location.id)

    if "previous_runs" in selected:
        record = _run(session, location.id, "previous_runs")
        try:
            payload = fetch_json(
                previous_runs_url(location.latitude, location.longitude, previous_days),
                ttl=timedelta(hours=6),
            )
            grouped = aggregate_previous_runs(payload)
            count = 0
            for lead, rows in grouped.items():
                count += replace_forecast_run(
                    session,
                    location,
                    f"previous_day{lead}",
                    retrieved_at,
                    retrieved_at,
                    rows,
                    "previous_run_lead",
                )
            _finish(record, "succeeded", count)
            summary["kinds"]["previous_runs"] = count
            summary["records"] += count
        except Exception as exc:
            _finish(record, "failed", 0, str(exc))
            summary["kinds"]["previous_runs"] = {"error": str(exc)}
            logger.exception("previous_run_ingestion_failed location_id=%s", location.id)

    return summary


def _location_zone(location: Location):
    try:
        return ZoneInfo(location.timezone or "UTC")
    except ZoneInfoNotFoundError:
        return timezone.utc


def catch_up_daily_history(session: Session, location: Location) -> int:
    """Store daily observations through yesterday when the archive is ahead of the database."""
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    latest = (
        session.query(WeatherObservation.observed_at)
        .filter_by(location_id=location.id, granularity="daily")
        .order_by(WeatherObservation.observed_at.desc())
        .limit(1)
        .scalar()
    )
    if latest is None:
        return 0
    latest_day = as_utc(latest).date()
    if latest_day >= yesterday:
        return 0
    start = latest_day + timedelta(days=1)
    settings = get_settings()
    payload = fetch_json(
        archive_daily_url(location.latitude, location.longitude, start.isoformat(), yesterday.isoformat()),
        ttl=timedelta(hours=settings.archive_cache_ttl_hours),
    )
    rows = parse_daily_archive(payload)
    try:
        count = upsert_observations(session, location.id, "daily", rows, datetime.now(timezone.utc))
    except IntegrityError:
        session.rollback()
        logger.info("daily_history_already_stored location_id=%s", location.id)
        return 0
    logger.info("caught_up_daily_history location_id=%s records=%s", location.id, count)
    return count


def ensure_fresh_current(session: Session, location: Location) -> None:
    """Refresh current conditions and the forecast when the stored snapshot is old or from a previous local day."""
    latest = (
        session.query(CurrentCondition)
        .filter_by(location_id=location.id)
        .order_by(CurrentCondition.retrieved_at.desc())
        .first()
    )
    now = datetime.now(timezone.utc)
    refresh = latest is None
    if latest is not None:
        retrieved = as_utc(latest.retrieved_at)
        refresh = now - retrieved > timedelta(minutes=get_settings().cache_ttl_minutes)
        if not refresh:
            zone = _location_zone(location)
            refresh = retrieved.astimezone(zone).date() < now.astimezone(zone).date()
    if not refresh:
        return
    logger.info("refreshing_current_conditions location_id=%s", location.id)
    ingest_location(session, location, kinds={"current", "forecast"})


def ingest_many(session: Session, locations: list[Location], **kwargs) -> list[dict]:
    summaries = []
    for index, location in enumerate(locations):
        if index:
            time.sleep(0.4)
        summaries.append(ingest_location(session, location, **kwargs))
    return summaries
