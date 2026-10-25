from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None
_ready = False


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    module_name = type(dbapi_connection).__module__
    if "sqlite" not in module_name:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_database(url: str | None = None, force: bool = False) -> None:
    global engine, SessionLocal, _ready
    if _ready and not force:
        return
    settings = get_settings()
    db_url = url or settings.resolved_database_url()
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if db_url in {"sqlite://", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
    if engine is not None:
        engine.dispose()
    engine = create_engine(db_url, **kwargs)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    if settings.auto_create_schema or db_url.startswith("sqlite"):
        from app.db import models  # noqa: F401
        from app.db.base import Base

        Base.metadata.create_all(bind=engine)
    _ready = True


def reset_database(url: str) -> None:
    global _ready
    _ready = False
    init_database(url, force=True)


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        init_database()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database() -> None:
    if engine is None:
        init_database()
    assert engine is not None
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
