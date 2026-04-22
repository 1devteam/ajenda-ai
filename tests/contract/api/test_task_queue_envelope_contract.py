from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import task as task_module
from backend.app.dependencies.db import get_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware


class _FakeSession:
    def execute(self, *_args, **_kwargs):
        return None


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = MagicMock(
        oidc_jwks_uri="https://example/jwks",
        oidc_issuer="https://example",
        oidc_audience="ajenda",
    )
    app.state.database_runtime = None

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(TenantContextMiddleware)

    app.include_router(task_module.router, prefix="/v1")

    def _override_db():
        yield _FakeSession()

    def _override_queue():
        return MagicMock()

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
    return app


def test_task_queue_route_requires_tenant_and_auth_under_middleware_stack() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    task_id = "3ac8e9a0-c351-41a5-95af-17dc9d7fd8c8"

    missing_tenant = client.post(f"/v1/tasks/{task_id}/queue")
    assert missing_tenant.status_code == 400

    missing_auth = client.post(
        f"/v1/tasks/{task_id}/queue",
        headers={"X-Tenant-Id": "3ac8e9a0-c351-41a5-95af-17dc9d7fd8c8"},
    )
    assert missing_auth.status_code == 401
