
"""Refresh current conditions and external forecasts, then evaluate alert rules.

This command does not retrain models.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.db import session as db_session
from app.db.models import Location
from app.services.alerts import evaluate_rules
from app.services.ingestion import ingest_many
from app.services.seed import seed_defaults


def main() -> None:
    db_session.init_database()
    seed_defaults()
    assert db_session.SessionLocal is not None
    session = db_session.SessionLocal()
    try:
        locations = session.query(Location).order_by(Location.id).all()
        summaries = ingest_many(session, locations, kinds={"current", "forecast"})
        result = evaluate_rules(session)
        session.commit()
        print({"ingestion": summaries, "alerts": result})
    finally:
        session.close()


if __name__ == "__main__":
    main()
