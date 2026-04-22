from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.services.execution_coordinator import CoordinationResult


def test_queue_task_route_returns_success_payload_when_task_is_queued() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = MagicMock()

    quota_svc = MagicMock()
    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(
        ok=True,
        task_id=task_id,
        state="queued",
    )

    with (
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

    quota_svc = MagicMock()
    coordinator = MagicMock()
    coordinator.queue_task.side_effect = ValueError("task not found for tenant")

    with (
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


def test_queue_task_route_returns_400_when_service_rejects_non_queueable_state() -> None:
    from backend.api.routes.task import queue_task

    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()

    db = MagicMock()
    queue = MagicMock()
    request = MagicMock()

    quota_svc = MagicMock()
    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(
        ok=False,
        task_id=task_id,
        state="blocked",
        reason="task queue rejected by policy",
    )

    with (
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
