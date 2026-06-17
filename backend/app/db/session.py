from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


def _engine_args(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        sqlite_path = database_url.replace("sqlite:///", "", 1)
        if sqlite_path not in {":memory:", ""}:
            Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        return {"connect_args": {"check_same_thread": False}}
    return {}


settings = get_settings()
engine = create_engine(settings.database_url, future=True, **_engine_args(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def make_test_sessionmaker() -> sessionmaker[Session]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    return sessionmaker(bind=test_engine, autocommit=False, autoflush=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
