from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import operations as operations_module
from backend.app.dependencies.db import get_db_session
from backend.app.dependencies.services import get_queue_adapter


class _RecoverySummary:
    def __init__(self, *, expired_lease_count: int, requeued_task_count: int, dead_lettered_count: int) -> None:
        self.expired_lease_count = expired_lease_count
        self.requeued_task_count = requeued_task_count
        self.dead_lettered_count = dead_lettered_count


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(operations_module.router, prefix="/v1")

    def _override_db():
        return MagicMock()

    def _override_queue():
        return MagicMock()

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
    return app


def test_recovery_route_is_public_and_returns_bounded_summary_without_tenant_or_auth() -> None:
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
