from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import health as health_module
from backend.api.routes import system as system_module
from backend.app.dependencies.db import get_db_session
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware


class _FakeSession:
    def execute(self, *_args, **_kwargs):
        return None


class _FakeDbRuntime:
    def session_scope(self):
        yield _FakeSession()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = MagicMock(
        oidc_jwks_uri="https://example/jwks", oidc_issuer="https://example", oidc_audience="ajenda"
    )
    app.state.database_runtime = _FakeDbRuntime()

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(TenantContextMiddleware)

    app.include_router(health_module.router)
    app.include_router(system_module.router, prefix="/v1")

    def _override_db():
        yield _FakeSession()

    app.dependency_overrides[get_db_session] = _override_db
    return app


def test_rg_health_root_probes_public() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    health = client.get("/health")
    readiness = client.get("/readiness")

    assert health.status_code == 200
    assert readiness.status_code == 200


def test_rg_system_status_envelope() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    # Public system probes should not require tenant/auth.
    assert client.get("/v1/system/health").status_code == 200
    assert client.get("/v1/system/readiness").status_code == 200

    # Tenant-scoped status must reject invalid envelope (missing tenant/auth).
    status = client.get("/v1/system/status")
    assert status.status_code in {400, 401}
