"""Evaluate enabled weather alert rules periodically while the API is running."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from app.db import session as db_session
from app.db.models import Location
from app.services.alerts import evaluate_rules
from app.services.ingestion import ensure_fresh_current

logger = logging.getLogger("weatheriq")
INTERVAL = timedelta(minutes=5)


def run_alert_check() -> dict:
    if db_session.SessionLocal is None:
        db_session.init_database()
    assert db_session.SessionLocal is not None
    session = db_session.SessionLocal()
    try:
        locations = session.query(Location).order_by(Location.id).all()
        for location in locations:
            try:
                ensure_fresh_current(session, location)
            except Exception:
                logger.exception("Scheduled weather refresh failed for location_id=%s", location.id)
                session.rollback()
        result = evaluate_rules(session)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def alert_evaluation_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            result = await asyncio.to_thread(run_alert_check)
            logger.info(
                "Scheduled alert evaluation completed created=%s skipped_duplicates=%s",
                result["created"],
                result["skipped_duplicates"],
            )
        except Exception:
            logger.exception("Scheduled alert evaluation failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=INTERVAL.total_seconds())
            return
        except TimeoutError:
            continue
