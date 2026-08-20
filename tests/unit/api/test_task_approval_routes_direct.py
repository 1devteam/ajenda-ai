from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.routes import admin, review_queue


def _request(*, actor: str = "reviewer-1") -> MagicMock:
    request = MagicMock()
    request.state.principal = SimpleNamespace(subject_id=actor, roles={"admin", "tenant_admin"})
    return request


def test_tenant_review_route_issues_expiring_grant_through_coordinator() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = SimpleNamespace(id=task_id, tenant_id=str(tenant_id), status="pending_review")
    session = MagicMock()
    queue = MagicMock()
    expiry = datetime(2099, 1, 1, tzinfo=UTC)
    with (
        patch.object(review_queue, "require_route_permission"),
        patch.object(review_queue.ExecutionTaskRepository, "get_for_tenant", return_value=task),
        patch.object(review_queue, "ExecutionCoordinator") as coordinator_cls,
    ):
        coordinator_cls.return_value.approve_review_and_queue.return_value = SimpleNamespace(state="queued")
        response = review_queue.approve_tenant_task(
            task_id=task_id,
            body=review_queue.TaskApprovalRequest(approval_expires_at=expiry),
            request=_request(),
            tenant_id=tenant_id,
            session=session,
            queue=queue,
        )

    assert response.status == "queued"
    coordinator_cls.return_value.approve_review_and_queue.assert_called_once_with(
        tenant_id=str(tenant_id),
        task_id=task_id,
        actor="reviewer-1",
        approval_expires_at=expiry,
    )
    session.commit.assert_called_once()


def test_tenant_review_route_does_not_disclose_other_tenant_task() -> None:
    with (
        patch.object(review_queue, "require_route_permission"),
        patch.object(review_queue.ExecutionTaskRepository, "get_for_tenant", return_value=None),
        pytest.raises(HTTPException) as exc_info,
    ):
        review_queue.approve_tenant_task(
            task_id=uuid.uuid4(),
            body=review_queue.TaskApprovalRequest(approval_expires_at=datetime(2099, 1, 1, tzinfo=UTC)),
            request=_request(),
            tenant_id=uuid.uuid4(),
            session=MagicMock(),
            queue=MagicMock(),
        )
    assert exc_info.value.status_code == 404


def test_tenant_review_route_revokes_through_locked_coordinator_path() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = SimpleNamespace(id=task_id, tenant_id=str(tenant_id), status="queued")
    session = MagicMock()
    with (
        patch.object(review_queue, "require_route_permission"),
        patch.object(review_queue.ExecutionTaskRepository, "get_for_tenant", return_value=task),
        patch.object(review_queue, "ExecutionCoordinator") as coordinator_cls,
    ):
        coordinator_cls.return_value.revoke_side_effect_approval.return_value = SimpleNamespace(state="queued")
        response = review_queue.revoke_tenant_task_approval(
            task_id=task_id,
            body=review_queue.TaskApprovalRevocationRequest(reason="operator cancellation"),
            request=_request(),
            tenant_id=tenant_id,
            session=session,
            queue=MagicMock(),
        )

    assert response.status == "queued"
    coordinator_cls.return_value.revoke_side_effect_approval.assert_called_once_with(
        tenant_id=str(tenant_id),
        task_id=task_id,
        actor="reviewer-1",
        reason="operator cancellation",
    )


def test_admin_review_route_passes_expiry_to_shared_coordinator() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = SimpleNamespace(id=task_id, tenant_id=str(tenant_id), status="pending_review")
    session = MagicMock()
    expiry = datetime(2099, 1, 1, tzinfo=UTC)
    with (
        patch.object(admin.ExecutionTaskRepository, "get", return_value=task),
        patch.object(admin, "ExecutionCoordinator") as coordinator_cls,
    ):
        coordinator_cls.return_value.approve_review_and_queue.return_value = SimpleNamespace(state="queued")
        response = admin.approve_task_review(
            tenant_id=tenant_id,
            task_id=task_id,
            body=admin.ApproveReviewRequest(approval_expires_at=expiry),
            request=_request(),
            db=session,
            queue=MagicMock(),
        )

    assert response.status == "queued"
    assert coordinator_cls.return_value.approve_review_and_queue.call_args.kwargs["approval_expires_at"] == expiry
