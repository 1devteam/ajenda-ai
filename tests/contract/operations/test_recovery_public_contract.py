from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import operations as operations_module
from backend.app.dependencies.db import get_db_session, get_request_tenant_id
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import Principal, PrincipalType


class _RecoverySummary:
    def __init__(self, *, expired_lease_count: int, requeued_task_count: int, dead_lettered_count: int) -> None:
        self.expired_lease_count = expired_lease_count
        self.requeued_task_count = requeued_task_count
        self.dead_lettered_count = dead_lettered_count


def _build_app(tenant_id: uuid.UUID, *, roles: tuple[str, ...] | None = ("operator",)) -> FastAPI:
    app = FastAPI()

    if roles is not None:

        @app.middleware("http")
        async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
            request.state.principal = Principal(
                subject_id="test-user",
                tenant_id=str(tenant_id),
                principal_type=PrincipalType.USER,
                roles=roles,
            )
            return await call_next(request)

    app.include_router(operations_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db():
        return MagicMock()

    def _override_queue():
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
    return app


def test_recovery_route_rejects_missing_route_principal_and_does_not_call_service() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id, roles=None)
    client = TestClient(app, raise_server_exceptions=False)

    service = MagicMock()
    with patch("backend.api.routes.operations.OperationsService", return_value=service):
        response = client.post("/v1/operations/recovery")

    assert response.status_code == 401
    service.trigger_recovery.assert_not_called()


def test_recovery_route_rejects_viewer_and_does_not_call_service() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id, roles=("viewer",))
    client = TestClient(app, raise_server_exceptions=False)

    service = MagicMock()
    with patch("backend.api.routes.operations.OperationsService", return_value=service):
        response = client.post("/v1/operations/recovery")

    assert response.status_code == 403
    service.trigger_recovery.assert_not_called()


def test_recovery_route_allows_operator_and_returns_bounded_summary() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id, roles=("operator",))
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
    service.trigger_recovery.assert_called_once_with()
