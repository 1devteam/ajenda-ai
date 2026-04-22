from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.api.routes import task as task_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.services.quota_enforcement import QuotaExceededError


def _build_task_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(task_module.router, prefix="/v1")

    def _override_tenant_id():
        return tenant_id

    def _override_db():
        return MagicMock()

    def _override_queue():
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
    return app


def _build_mission_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(mission_module.router, prefix="/v1")

    def _override_tenant_id():
        return tenant_id

    def _override_db():
        return MagicMock()

    def _override_queue():
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
    return app


def test_task_queue_contract_returns_structured_429_on_quota_exceeded() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_task_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    quota_svc = MagicMock()
    quota_svc.check_and_record_task_creation.side_effect = QuotaExceededError(
        field="tasks_per_month",
        limit=50,
        current=50,
        plan="free",
    )

    with patch("backend.api.routes.task.QuotaEnforcementService", return_value=quota_svc):
        response = client.post(f"/v1/tasks/{task_id}/queue")

    assert response.status_code == 429
    assert response.json() == {
        "detail": {
            "code": "QUOTA_EXCEEDED",
            "field": "tasks_per_month",
            "limit": 50,
            "current": 50,
            "plan": "free",
            "message": "You have reached the tasks_per_month limit (50) for the 'free' plan. Upgrade to continue.",
        }
    }


def test_mission_queue_contract_returns_structured_429_on_quota_exceeded() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_mission_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    task = MagicMock()
    task.id = uuid.uuid4()
    task.tenant_id = str(tenant_id)
    task.mission_id = mission_id
    task.status = "planned"

    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [task]

    quota_svc = MagicMock()
    quota_svc.check_and_record_task_creation.side_effect = QuotaExceededError(
        field="tasks_per_month",
        limit=50,
        current=49,
        plan="free",
    )

    with (
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
    ):
        response = client.post(f"/v1/missions/{mission_id}/queue")

    assert response.status_code == 429
    assert response.json() == {
        "detail": {
            "code": "QUOTA_EXCEEDED",
            "field": "tasks_per_month",
            "limit": 50,
            "current": 49,
            "plan": "free",
            "message": "You have reached the tasks_per_month limit (50) for the 'free' plan. Upgrade to continue.",
        }
    }
