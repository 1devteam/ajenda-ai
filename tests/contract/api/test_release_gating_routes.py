from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import health as health_module
from backend.api.routes import operations as operations_module
from backend.api.routes import system as system_module
from backend.app.dependencies.db import get_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware


class _FakeSession:
    def execute(self, *_args, **_kwargs):
        return None


class _RecoverySummary:
    def __init__(self, *, expired_lease_count: int, requeued_task_count: int, dead_lettered_count: int) -> None:
        self.expired_lease_count = expired_lease_count
        self.requeued_task_count = requeued_task_count
        self.dead_lettered_count = dead_lettered_count


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = MagicMock(
        oidc_jwks_uri="https://example/jwks", oidc_issuer="https://example", oidc_audience="ajenda"
    )
    app.state.database_runtime = None

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(TenantContextMiddleware)

    app.include_router(health_module.router)
    app.include_router(system_module.router, prefix="/v1")
    app.include_router(operations_module.router, prefix="/v1")

    def _override_db():
        yield _FakeSession()

    def _override_queue():
        return MagicMock()

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
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

    assert client.get("/v1/system/health").status_code == 200
    assert client.get("/v1/system/readiness").status_code == 200

    missing_tenant = client.get("/v1/system/status")
    assert missing_tenant.status_code == 400

    missing_auth = client.get(
        "/v1/system/status",
        headers={"X-Tenant-Id": "3ac8e9a0-c351-41a5-95af-17dc9d7fd8c8"},
    )
    assert missing_auth.status_code == 401


def test_rg_recovery_route_remains_public_under_middleware_stack() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    service = MagicMock()
    service.trigger_recovery.return_value = _RecoverySummary(
        expired_lease_count=2,
        requeued_task_count=1,
        dead_lettered_count=1,
    )

    with patch("backend.api.routes.operations.OperationsService", return_value=service):
        response = client.post("/v1/operations/recovery")

    assert response.status_code == 200
    assert response.json() == {
        "expired_lease_count": 2,
        "requeued_task_count": 1,
        "dead_lettered_count": 1,
    }


def test_rg_recovery_route_fails_closed_on_service_exception() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    service = MagicMock()
    service.trigger_recovery.side_effect = RuntimeError("recovery failed")

    with patch("backend.api.routes.operations.OperationsService", return_value=service):
        response = client.post("/v1/operations/recovery")

    assert response.status_code == 500
    service.trigger_recovery.assert_called_once_with()


def test_rg_dead_letter_inspection_route_fails_closed_on_service_exception() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    service = MagicMock()
    service.inspect_dead_letter.side_effect = RuntimeError("inspection failed")

    with patch("backend.api.routes.operations.OperationsService", return_value=service):
        response = client.get(
            "/v1/operations/dead-letter",
            headers={
                "X-Tenant-Id": "3ac8e9a0-c351-41a5-95af-17dc9d7fd8c8",
                "Authorization": "Bearer test-token",
            },
        )

    assert response.status_code == 500
    service.inspect_dead_letter.assert_called_once()


def test_rg_dead_letter_routes_require_valid_tenant_and_auth_envelope() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    task_id = "3ac8e9a0-c351-41a5-95af-17dc9d7fd8c8"

    missing_tenant_inspection = client.get("/v1/operations/dead-letter")
    missing_tenant_retry = client.post(f"/v1/operations/dead-letter/{task_id}/retry")
    assert missing_tenant_inspection.status_code == 400
    assert missing_tenant_retry.status_code == 400

    missing_auth_inspection = client.get(
        "/v1/operations/dead-letter",
        headers={"X-Tenant-Id": "3ac8e9a0-c351-41a5-95af-17dc9d7fd8c8"},
    )
    missing_auth_retry = client.post(
        f"/v1/operations/dead-letter/{task_id}/retry",
        headers={"X-Tenant-Id": "3ac8e9a0-c351-41a5-95af-17dc9d7fd8c8"},
    )
    assert missing_auth_inspection.status_code == 401
    assert missing_auth_retry.status_code == 401
