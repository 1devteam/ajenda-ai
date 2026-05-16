from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI

from backend.api.routes import health as health_module
from backend.api.routes import operations as operations_module
from backend.api.routes import system as system_module
from backend.app.dependencies.db import get_database_runtime, get_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware


class _FakeSession:
    def execute(self, *_args, **_kwargs):
        return None


class _FakeDatabaseRuntime:
    def __init__(self, ready: bool = True):
        self.ready = ready

    def ping(self) -> bool:
        return self.ready


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = MagicMock(
        oidc_jwks_uri="https://example/jwks",
        oidc_issuer="https://example",
        oidc_audience="ajenda",
    )

    # ✅ THIS IS THE CRITICAL FIX
    app.state.database_runtime = _FakeDatabaseRuntime()

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(TenantContextMiddleware)

    app.include_router(health_module.router)
    app.include_router(system_module.router, prefix="/v1")
    app.include_router(operations_module.router, prefix="/v1")

    def _override_db():
        yield _FakeSession()

    def _override_queue():
        mock = MagicMock()
        mock.ping.return_value = True
        return mock

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue

    # ✅ ensure dependency path is consistent
    app.dependency_overrides[get_database_runtime] = lambda: app.state.database_runtime

    return app
