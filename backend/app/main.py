from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.init_db import init_db
from app.observability import configure_sentry
from app.routers import catalog, health, imports, ingredients, risk, scan, sources


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(get_settings())
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_sentry(settings)
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api_prefix = "/api/v1"
    app.include_router(health.router, prefix=api_prefix)
    app.include_router(catalog.router, prefix=api_prefix)
    app.include_router(ingredients.router, prefix=api_prefix)
    app.include_router(risk.router, prefix=api_prefix)
    app.include_router(scan.router, prefix=api_prefix)
    app.include_router(imports.router, prefix=api_prefix)
    app.include_router(sources.router, prefix=api_prefix)
    return app


app = create_app()
