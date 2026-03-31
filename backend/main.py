from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.router import build_api_router
from backend.app.config import get_settings
from backend.app.logging import configure_logging
from backend.db.session import DatabaseRuntime
from backend.queue import build_queue_adapter


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    database_runtime = DatabaseRuntime(settings)
    queue_adapter = build_queue_adapter(settings)
    if not queue_adapter.ping():
        raise RuntimeError(f"Queue adapter {settings.queue_adapter} failed startup ping")
    app.state.settings = settings
    app.state.database_runtime = database_runtime
    app.state.queue_adapter = queue_adapter
    try:
        yield
    finally:
        database_runtime.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(build_api_router())
    return app


app = create_app()
