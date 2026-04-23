from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import task as task_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.services.execution_coordinator import CoordinationResult


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
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


def test_task_queue_contract_returns_success_payload() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    task = MagicMock()
    task.tenant_id = str(tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    quota_svc = MagicMock()
    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(
        ok=True,
        task_id=task_id,
        state="queued",
    )

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.task.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.task.ExecutionCoordinator", return_value=coordinator),
    ):
        response = client.post(f"/v1/tasks/{task_id}/queue")

    assert response.status_code == 200
    assert response.json() == {"task_id": str(task_id), "state": "queued"}
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id)
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)


def test_task_queue_contract_returns_400_when_task_not_found_for_tenant() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    task_repo = MagicMock()
    task_repo.get.return_value = None
    quota_svc = MagicMock()
    coordinator = MagicMock()

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.task.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.task.ExecutionCoordinator", return_value=coordinator),
    ):
        response = client.post(f"/v1/tasks/{task_id}/queue")

    assert response.status_code == 400
    assert response.json() == {"detail": "task not found for tenant"}
    quota_svc.check_and_record_task_creation.assert_not_called()
    coordinator.queue_task.assert_not_called()


def test_task_queue_contract_returns_400_when_task_belongs_to_other_tenant() -> None:
    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    task = MagicMock()
    task.tenant_id = str(other_tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    quota_svc = MagicMock()
    coordinator = MagicMock()

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.task.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.task.ExecutionCoordinator", return_value=coordinator),
    ):
        response = client.post(f"/v1/tasks/{task_id}/queue")

    assert response.status_code == 400
    assert response.json() == {"detail": "task not found for tenant"}
    quota_svc.check_and_record_task_creation.assert_not_called()
    coordinator.queue_task.assert_not_called()


def test_task_queue_contract_returns_400_when_coordinator_raises_value_error_after_quota() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    task = MagicMock()
    task.tenant_id = str(tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    quota_svc = MagicMock()
    coordinator = MagicMock()
    coordinator.queue_task.side_effect = ValueError("task is not queueable")

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.task.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.task.ExecutionCoordinator", return_value=coordinator),
    ):
        response = client.post(f"/v1/tasks/{task_id}/queue")

    assert response.status_code == 400
    assert response.json() == {"detail": "task is not queueable"}
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id)
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)


def test_task_queue_contract_returns_500_when_coordinator_raises_unexpected_exception_after_quota() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    task = MagicMock()
    task.tenant_id = str(tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    quota_svc = MagicMock()
    coordinator = MagicMock()
    coordinator.queue_task.side_effect = RuntimeError("queue path blew up")

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.task.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.task.ExecutionCoordinator", return_value=coordinator),
    ):
        response = client.post(f"/v1/tasks/{task_id}/queue")

    assert response.status_code == 500
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id)
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)


def test_task_queue_contract_returns_400_when_service_rejects_queue_attempt() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    task = MagicMock()
    task.tenant_id = str(tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    quota_svc = MagicMock()
    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(
        ok=False,
        task_id=task_id,
        state="blocked",
        reason="task queue rejected by policy",
    )

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.task.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.task.ExecutionCoordinator", return_value=coordinator),
    ):
        response = client.post(f"/v1/tasks/{task_id}/queue")

    assert response.status_code == 400
    assert response.json() == {"detail": "task queue rejected by policy"}
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id)
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)


def test_task_queue_contract_returns_400_when_task_is_routed_to_pending_review() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    task = MagicMock()
    task.tenant_id = str(tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    quota_svc = MagicMock()
    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(
        ok=False,
        task_id=task_id,
        state="pending_review",
        reason="human review required",
    )

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.task.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.task.ExecutionCoordinator", return_value=coordinator),
    ):
        response = client.post(f"/v1/tasks/{task_id}/queue")

    assert response.status_code == 400
    assert response.json() == {"detail": "human review required"}
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id)
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)
