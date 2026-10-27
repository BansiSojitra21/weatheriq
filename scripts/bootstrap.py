"""Create the local database, ingest Open-Meteo data, train models, and score alerts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.db import session as db_session
from app.db.models import Location
from app.services.alerts import evaluate_rules
from app.services.anomaly_service import detect_anomalies
from app.services.ingestion import ingest_many
from app.services.seed import seed_defaults


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap WeatherIQ local data and models.")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--history-days", type=int, default=None)
    parser.add_argument("--hourly-days", type=int, default=None)
    args = parser.parse_args()
    db_session.init_database()
    seed_defaults()
    assert db_session.SessionLocal is not None
    session = db_session.SessionLocal()
    try:
        if not args.skip_ingest:
            locations = session.query(Location).order_by(Location.id).all()
            summaries = ingest_many(
                session,
                locations,
                history_days=args.history_days,
                hourly_days=args.hourly_days,
            )
            session.commit()
            for summary in summaries:
                print(summary)
        if not args.skip_train:
            session.close()
            from scripts.train_models import train_from_database

            print(train_from_database())
            session = db_session.SessionLocal()
        detect_anomalies(session, window_days=30)
        print(evaluate_rules(session))
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    main()
