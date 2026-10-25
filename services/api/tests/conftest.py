from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db import session as db_session
from app.main import app
from app.services.seed import seed_defaults


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("WEATHERIQ_API_KEY", "test-key")
    monkeypatch.setenv("WEATHERIQ_ANOMALY_SCHEDULE_ENABLED", "false")
    monkeypatch.setenv("WEATHERIQ_ALERT_SCHEDULE_ENABLED", "false")
    get_settings.cache_clear()
    url = "sqlite:///" + (tmp_path / "test.db").as_posix()
    db_session.reset_database(url)
    assert db_session.SessionLocal is not None
    session = db_session.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(database):
    seed_defaults(database)
    with TestClient(app) as test_client:
        yield test_client
