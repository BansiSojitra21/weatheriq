import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.db import session as db_session
from app.db.models import Location
from app.services.ingestion import ingest_location
from app.services.anomaly_service import detect_anomalies
from app.services.alerts import evaluate_rules

os.environ["WEATHERIQ_DATABASE_URL"] = (
    "postgresql+psycopg://neondb_owner:npg_TUlRwFC1hnv0@ep-still-glade-b7sdirvt-pooler.c-13.us-east-1.aws.neon.tech/neondb?sslmode=require"
)

db_session.init_database()
session = db_session.SessionLocal()
locations = session.query(Location).order_by(Location.id).all()
print(f"Populating 90-day history for {len(locations)} locations...")

for loc in locations:
    try:
        res = ingest_location(session, loc, kinds={"history"}, history_days=90)
        session.commit()
        print(f"[{loc.id}] {loc.name}: {res.get('records', 0)} history records saved")
        time.sleep(0.3)
    except Exception as e:
        print(f"[{loc.id}] {loc.name} error: {e}")

try:
    print("Evaluating anomalies and alert rules...")
    detect_anomalies(session, window_days=30)
    evaluate_rules(session)
    session.commit()
    print("Anomalies and alert rules evaluated successfully!")
except Exception as e:
    print(f"Evaluation error: {e}")

session.close()
print("All historical data populated!")
