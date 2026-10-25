"""Run exploratory anomaly detection once per day while the API process is up."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.db import session as db_session
from app.db.models import AppSetting
from app.services.anomaly_service import detect_anomalies

logger = logging.getLogger("weatheriq")

SCHEDULE_KEY = "anomaly_schedule"
INTERVAL = timedelta(days=1)
RETRY = timedelta(hours=1)


def seconds_until_due(now: datetime, last_run: datetime | None, interval: timedelta = INTERVAL) -> float:
    if last_run is None:
        return 0.0
    remaining = interval - (now - last_run)
    return max(0.0, remaining.total_seconds())


def _parse_ran_at(value: dict | None) -> datetime | None:
    if not value:
        return None
    raw = value.get("ran_at")
    if not raw:
        return None
    parsed = datetime.fromisoformat(str(raw))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def seconds_until_next_run(now: datetime | None = None) -> float:
    if db_session.SessionLocal is None:
        db_session.init_database()
    assert db_session.SessionLocal is not None
    session = db_session.SessionLocal()
    try:
        row = session.get(AppSetting, SCHEDULE_KEY)
        last_run = None if row is None else _parse_ran_at(row.value)
        return seconds_until_due(now or datetime.now(timezone.utc), last_run)
    finally:
        session.close()


def run_if_due(now: datetime | None = None) -> dict | None:
    """Detect anomalies for every location when the last run is at least a day old."""
    if db_session.SessionLocal is None:
        db_session.init_database()
    assert db_session.SessionLocal is not None
    session = db_session.SessionLocal()
    current = now or datetime.now(timezone.utc)
    try:
        schedule = session.get(AppSetting, SCHEDULE_KEY)
        last_run = None if schedule is None else _parse_ran_at(schedule.value)
        if seconds_until_due(current, last_run) > 0:
            return None
        settings = session.get(AppSetting, "app")
        stored = {} if settings is None else dict(settings.value)
        threshold = float(stored.get("anomaly_z_threshold", 3.5))
        window_days = int(stored.get("anomaly_window_days", 30))
        result = detect_anomalies(session, threshold=threshold, window_days=window_days)
        payload = {"ran_at": current.isoformat()}
        if schedule is None:
            session.add(AppSetting(key=SCHEDULE_KEY, value=payload, updated_at=current))
        else:
            schedule.value = payload
            schedule.updated_at = current
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def anomaly_detection_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            delay = await asyncio.to_thread(seconds_until_next_run)
        except Exception:
            logger.exception("Could not read the anomaly detection schedule")
            delay = RETRY.total_seconds()
        if delay > 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                return
            except TimeoutError:
                pass
        if stop.is_set():
            return
        try:
            result = await asyncio.to_thread(run_if_due)
        except Exception:
            logger.exception("Daily anomaly detection failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=RETRY.total_seconds())
                return
            except TimeoutError:
                continue
        if result is not None:
            logger.info("Daily anomaly detection updated %s events", result.get("created_or_updated"))
