from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
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


def _apply_sqlite_pragmas(engine) -> None:
    """Tune SQLite for write-heavy bulk imports and concurrent reads.

    WAL lets readers proceed while a writer is active (so monitoring queries no
    longer hit "database is locked"), and synchronous=NORMAL drops the per-commit
    fsync to one-per-checkpoint — the dominant cost when importing pages that each
    issue 150-300 row operations. A large negative cache_size keeps the working
    set in memory.
    """

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # pragma: no cover - connection hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA cache_size=-131072")  # ~128 MB page cache
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()


settings = get_settings()
engine = create_engine(settings.database_url, future=True, **_engine_args(settings.database_url))
if settings.database_url.startswith("sqlite"):
    _apply_sqlite_pragmas(engine)
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
