from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.services.execution_coordinator import CoordinationResult
from backend.services.quota_enforcement import QuotaExceededError


def test_queue_task_route_returns_success_payload_when_task_is_queued() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = MagicMock()

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
        result = queue_task(
            task_id=task_id,
            request=request,
            tenant_id=tenant_id,
            db=db,
            queue=queue,
        )

    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id)
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)
    assert result == {"task_id": str(task_id), "state": "queued"}


def test_queue_task_route_returns_400_when_task_not_found_for_tenant() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = MagicMock()

    task_repo = MagicMock()
    task_repo.get.return_value = None
    quota_svc = MagicMock()
    coordinator = MagicMock()

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.task.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.task.ExecutionCoordinator", return_value=coordinator),
    ):
        with pytest.raises(HTTPException) as exc_info:
            queue_task(
                task_id=task_id,
                request=request,
                tenant_id=tenant_id,
                db=db,
                queue=queue,
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "task not found for tenant"
    quota_svc.check_and_record_task_creation.assert_not_called()
    coordinator.queue_task.assert_not_called()


def test_queue_task_route_returns_400_when_task_belongs_to_other_tenant() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = MagicMock()

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
        with pytest.raises(HTTPException) as exc_info:
            queue_task(
                task_id=task_id,
                request=request,
                tenant_id=tenant_id,
                db=db,
                queue=queue,
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "task not found for tenant"
    quota_svc.check_and_record_task_creation.assert_not_called()
    coordinator.queue_task.assert_not_called()


def test_queue_task_route_returns_structured_429_when_quota_exceeded_for_valid_tenant_task() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = MagicMock()

    task = MagicMock()
    task.tenant_id = str(tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    quota_svc = MagicMock()
    quota_svc.check_and_record_task_creation.side_effect = QuotaExceededError(
        field="tasks_per_month",
        limit=50,
        current=50,
        plan="free",
    )
    coordinator = MagicMock()

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.task.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.task.ExecutionCoordinator", return_value=coordinator),
    ):
        with pytest.raises(HTTPException) as exc_info:
            queue_task(
                task_id=task_id,
                request=request,
                tenant_id=tenant_id,
                db=db,
                queue=queue,
            )

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == {
        "code": "QUOTA_EXCEEDED",
        "field": "tasks_per_month",
        "limit": 50,
        "current": 50,
        "plan": "free",
        "message": "You have reached the tasks_per_month limit (50) for the 'free' plan. Upgrade to continue.",
    }
    coordinator.queue_task.assert_not_called()


def test_queue_task_route_returns_400_when_coordinator_raises_value_error_after_quota() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = MagicMock()

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
        with pytest.raises(HTTPException) as exc_info:
            queue_task(
                task_id=task_id,
                request=request,
                tenant_id=tenant_id,
                db=db,
                queue=queue,
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "task is not queueable"
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id)
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)


def test_queue_task_route_returns_400_when_service_rejects_non_queueable_state() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = MagicMock()

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
        with pytest.raises(HTTPException) as exc_info:
            queue_task(
                task_id=task_id,
                request=request,
                tenant_id=tenant_id,
                db=db,
                queue=queue,
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "task queue rejected by policy"
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id)
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)


def test_queue_task_route_returns_400_when_task_is_routed_to_pending_review() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = MagicMock()

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
        with pytest.raises(HTTPException) as exc_info:
            queue_task(
                task_id=task_id,
                request=request,
                tenant_id=tenant_id,
                db=db,
                queue=queue,
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "human review required"
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id)
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)
