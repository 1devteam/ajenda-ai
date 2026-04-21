from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.operations import router
from backend.app.dependencies.db import get_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.services.runtime_maintainer import RecoverySummary


class _RecoveryOpsService:
    def trigger_recovery(self) -> RecoverySummary:
        return RecoverySummary(
            expired_lease_count=2,
            requeued_task_count=1,
            dead_lettered_count=3,
        )


def test_recovery_route_returns_full_summary_payload(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/v1")

    def _db_dep():
        yield MagicMock()

    def _queue_dep():
        return MagicMock()

    app.dependency_overrides[get_db_session] = _db_dep
    app.dependency_overrides[get_queue_adapter] = _queue_dep

    monkeypatch.setattr(
        "backend.api.routes.operations.OperationsService",
        lambda *_args, **_kwargs: _RecoveryOpsService(),
    )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/v1/operations/recovery")

    assert response.status_code == 200
    assert response.json() == {
        "expired_lease_count": 2,
        "requeued_task_count": 1,
        "dead_lettered_count": 3,
    }
