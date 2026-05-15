from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.services.execution_coordinator import CoordinationResult


class _AnyTenantId:
    def __eq__(self, _other: object) -> bool:
        return True

    def __ne__(self, _other: object) -> bool:
        return False


def _authorized_request() -> MagicMock:
    request = MagicMock()
    request.state.principal = SimpleNamespace(
        subject_id="test-user",
        tenant_id=_AnyTenantId(),
        roles=("operator",),
        permissions=frozenset(),
    )
    return request


def test_queue_task_route_returns_success_payload_when_task_is_queued() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = _authorized_request()

    task = MagicMock()
    task.tenant_id = str(tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(
        ok=True,
        task_id=task_id,
        state="queued",
    )

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.task.ExecutionCoordinator", return_value=coordinator),
    ):
        result = queue_task(
            task_id=task_id,
            request=request,
            tenant_id=tenant_id,
            db=db,
            queue=queue,
        )

    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)
    assert result == {"task_id": str(task_id), "state": "queued"}


def test_queue_task_route_returns_400_when_task_not_found_for_tenant() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = _authorized_request()

    task_repo = MagicMock()
    task_repo.get.return_value = None
    coordinator = MagicMock()

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
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
    coordinator.queue_task.assert_not_called()


def test_queue_task_route_returns_400_when_task_belongs_to_other_tenant() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = _authorized_request()

    task = MagicMock()
    task.tenant_id = str(other_tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    coordinator = MagicMock()

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
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
    coordinator.queue_task.assert_not_called()


def test_queue_task_route_does_not_meter_existing_task_queueing() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = _authorized_request()

    task = MagicMock()
    task.tenant_id = str(tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(ok=True, task_id=task_id, state="queued")

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.task.ExecutionCoordinator", return_value=coordinator),
    ):
        result = queue_task(
            task_id=task_id,
            request=request,
            tenant_id=tenant_id,
            db=db,
            queue=queue,
        )

    assert result == {"task_id": str(task_id), "state": "queued"}
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)


def test_queue_task_route_returns_400_when_coordinator_raises_value_error_after_ownership_check() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = _authorized_request()

    task = MagicMock()
    task.tenant_id = str(tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    coordinator = MagicMock()
    coordinator.queue_task.side_effect = ValueError("task is not queueable")

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
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
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)


def test_queue_task_route_returns_500_when_coordinator_raises_unexpected_exception_after_ownership_check() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = _authorized_request()

    task = MagicMock()
    task.tenant_id = str(tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    coordinator = MagicMock()
    coordinator.queue_task.side_effect = RuntimeError("queue path blew up")

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.task.ExecutionCoordinator", return_value=coordinator),
    ):
        with pytest.raises(RuntimeError, match="queue path blew up"):
            queue_task(
                task_id=task_id,
                request=request,
                tenant_id=tenant_id,
                db=db,
                queue=queue,
            )

    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)


def test_queue_task_route_returns_400_when_service_rejects_non_queueable_state() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = _authorized_request()

    task = MagicMock()
    task.tenant_id = str(tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(
        ok=False,
        task_id=task_id,
        state="blocked",
        reason="task queue rejected by policy",
    )

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
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
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)


def test_queue_task_route_returns_400_when_task_is_routed_to_pending_review() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = _authorized_request()

    task = MagicMock()
    task.tenant_id = str(tenant_id)

    task_repo = MagicMock()
    task_repo.get.return_value = task
    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(
        ok=False,
        task_id=task_id,
        state="pending_review",
        reason="human review required",
    )

    with (
        patch("backend.api.routes.task.ExecutionTaskRepository", return_value=task_repo),
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
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)
