from collections.abc import Generator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import create_app
from app.services.enrichment import seed_reference_sources_and_rules
from app.services.importers.open_beauty_facts import import_open_beauty_facts


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    with TestingSessionLocal() as db:
        seed_reference_sources_and_rules(db)
        import_open_beauty_facts(db, source_path=None, limit=10)
        seed_reference_sources_and_rules(db)
        db.commit()
        yield db


@pytest.fixture()
def api_app(db_session: Session) -> FastAPI:
    @asynccontextmanager
    async def noop_lifespan(app: FastAPI):
        yield

    app = create_app()
    app.router.lifespan_context = noop_lifespan

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.fixture()
def client(api_app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(api_app) as test_client:
        yield test_client
