from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.domain.enums import ExecutionTaskState
from backend.services.execution_coordinator import ExecutionCoordinator


def _allowed_decision() -> SimpleNamespace:
    return SimpleNamespace(execution_allowed=True, mode="NORMAL", reason=None)


def _policy_denied() -> SimpleNamespace:
    return SimpleNamespace(
        allowed=False,
        reason="human review required",
    )


def _task(*, tenant_id: str, status: str = ExecutionTaskState.PLANNED.value) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        fleet_id=None,
        branch_id=None,
        status=status,
        metadata_json={"task_type": "echo"},
        compliance_category="regulated_decision",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )


def _coordinator_with_policy_review_required(
    *,
    task: SimpleNamespace,
    queue: MagicMock | None = None,
) -> ExecutionCoordinator:
    session = MagicMock()
    queue = queue or MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()
    coordinator._tasks.get.return_value = task
    coordinator._governor = MagicMock()
    coordinator._governor.evaluate.return_value = _allowed_decision()
    coordinator._policy = MagicMock()
    coordinator._policy.evaluate_task.return_value = _policy_denied()
    coordinator._governance = MagicMock()
    coordinator._audit = MagicMock()
    return coordinator


def test_queue_task_policy_review_moves_task_to_pending_review_without_enqueueing() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)
    queue = MagicMock()
    coordinator = _coordinator_with_policy_review_required(task=task, queue=queue)

    result = coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    assert result.ok is False
    assert result.task_id == task.id
    assert result.state == ExecutionTaskState.PENDING_REVIEW.value
    assert result.reason == "human review required"
    assert task.status == ExecutionTaskState.PENDING_REVIEW.value
    assert task.requires_human_review is True
    queue.enqueue_task.assert_not_called()


def test_queue_task_policy_review_emits_governance_evidence() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)
    coordinator = _coordinator_with_policy_review_required(task=task)

    coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    coordinator._governance.append.assert_called_once()
    governance_event = coordinator._governance.append.call_args.args[0]
    assert governance_event.tenant_id == tenant_id
    assert governance_event.mission_id == task.mission_id
    assert governance_event.event_type == "compliance_review_required"
    assert governance_event.actor == "policy_guardian"
    assert governance_event.decision == "human review required"
    assert governance_event.payload_json == {
        "task_id": str(task.id),
        "compliance_category": "regulated_decision",
        "jurisdiction": "US-ALL",
        "reason": "human review required",
    }


def test_queue_task_policy_review_emits_audit_evidence() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)
    coordinator = _coordinator_with_policy_review_required(task=task)

    coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    coordinator._audit.append.assert_called_once()
    audit_event = coordinator._audit.append.call_args.args[0]
    assert audit_event.tenant_id == tenant_id
    assert audit_event.mission_id == task.mission_id
    assert audit_event.category == "compliance"
    assert audit_event.action == "task_pending_review"
    assert audit_event.actor == "policy_guardian"
    assert audit_event.payload_json == {
        "task_id": str(task.id),
        "reason": "human review required",
    }


def test_queue_task_policy_review_flushes_state_and_evidence() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)
    coordinator = _coordinator_with_policy_review_required(task=task)

    coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    assert coordinator._session.flush.call_count == 2


def test_queue_task_policy_review_evaluates_policy_after_runtime_governor_allows() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)
    coordinator = _coordinator_with_policy_review_required(task=task)

    coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    coordinator._governor.evaluate.assert_called_once()
    coordinator._policy.evaluate_task.assert_called_once_with(task)
