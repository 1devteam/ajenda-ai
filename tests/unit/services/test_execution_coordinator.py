from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.domain.enums import ExecutionTaskState
from backend.queue.base import QueueOperationResult
from backend.services.execution_coordinator import ExecutionCoordinator


def _allowed_decision() -> SimpleNamespace:
    return SimpleNamespace(execution_allowed=True, mode="NORMAL", reason=None)


def _policy_allowed() -> SimpleNamespace:
    return SimpleNamespace(allowed=True, reason=None)


def _task(*, tenant_id: str, status: str = ExecutionTaskState.PLANNED.value) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        fleet_id=None,
        branch_id=None,
        status=status,
        metadata_json={"task_type": "echo"},
    )


def _coordinator_with_task(*, task: SimpleNamespace, queue: MagicMock | None = None) -> ExecutionCoordinator:
    session = MagicMock()
    queue = queue or MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()
    coordinator._tasks.get.return_value = task
    coordinator._governor = MagicMock()
    coordinator._governor.evaluate.return_value = _allowed_decision()
    coordinator._policy = MagicMock()
    coordinator._policy.evaluate_task.return_value = _policy_allowed()
    coordinator._governance = MagicMock()
    coordinator._audit = MagicMock()
    return coordinator


def test_require_task_raises_when_task_missing() -> None:
    session = MagicMock()
    queue = MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()
    coordinator._tasks.get.return_value = None

    with pytest.raises(ValueError, match="task not found for tenant"):
        coordinator._require_task(task_id=uuid.uuid4(), tenant_id=str(uuid.uuid4()))


def test_require_task_raises_when_task_belongs_to_other_tenant() -> None:
    session = MagicMock()
    queue = MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()

    task = MagicMock()
    task.tenant_id = str(uuid.uuid4())
    coordinator._tasks.get.return_value = task

    with pytest.raises(ValueError, match="task not found for tenant"):
        coordinator._require_task(task_id=uuid.uuid4(), tenant_id=str(uuid.uuid4()))


def test_require_task_returns_task_for_matching_tenant() -> None:
    session = MagicMock()
    queue = MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()

    tenant_id = str(uuid.uuid4())
    task = MagicMock()
    task.tenant_id = tenant_id
    coordinator._tasks.get.return_value = task

    result = coordinator._require_task(task_id=uuid.uuid4(), tenant_id=tenant_id)

    assert result is task


def test_queue_task_restores_previous_planned_state_when_enqueue_fails() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.PLANNED.value)
    queue = MagicMock()
    queue.enqueue_task.return_value = QueueOperationResult(ok=False, reason="redis unavailable")
    coordinator = _coordinator_with_task(task=task, queue=queue)

    with pytest.raises(ValueError, match="redis unavailable"):
        coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    assert task.status == ExecutionTaskState.PLANNED.value
    assert coordinator._session.flush.call_count == 2
    coordinator._audit.append.assert_not_called()


def test_queue_task_enqueues_after_transitioning_planned_task_to_queued() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.PLANNED.value)
    queue = MagicMock()
    queue.enqueue_task.return_value = QueueOperationResult(ok=True)
    coordinator = _coordinator_with_task(task=task, queue=queue)

    result = coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    assert result.ok is True
    assert result.state == ExecutionTaskState.QUEUED.value
    assert task.status == ExecutionTaskState.QUEUED.value
    queue.enqueue_task.assert_called_once()
    queued_message = queue.enqueue_task.call_args.args[0]
    assert queued_message.tenant_id == tenant_id
    assert queued_message.task_id == task.id
    assert queued_message.payload == task.metadata_json
    coordinator._audit.append.assert_called_once()


def test_queue_task_preserves_previous_retryable_state_on_enqueue_failure() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.FAILED.value)
    queue = MagicMock()
    queue.enqueue_task.return_value = QueueOperationResult(ok=False, reason=None)
    coordinator = _coordinator_with_task(task=task, queue=queue)

    with pytest.raises(ValueError, match="queue enqueue failed"):
        coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    assert task.status == ExecutionTaskState.FAILED.value
    coordinator._audit.append.assert_not_called()


def test_mark_dead_letter_restores_previous_state_when_queue_move_fails() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.FAILED.value)
    queue = MagicMock()
    queue.move_to_dead_letter.return_value = QueueOperationResult(ok=False, reason="redis dead-letter unavailable")
    coordinator = _coordinator_with_task(task=task, queue=queue)

    with pytest.raises(ValueError, match="redis dead-letter unavailable"):
        coordinator.mark_dead_letter(
            tenant_id=tenant_id,
            task_id=task.id,
            reason="retry budget exhausted",
        )

    assert task.status == ExecutionTaskState.FAILED.value
    coordinator._governance.append.assert_not_called()


def test_mark_dead_letter_moves_task_to_dead_letter_and_emits_governance_evidence() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.FAILED.value)
    queue = MagicMock()
    queue.move_to_dead_letter.return_value = QueueOperationResult(ok=True)
    coordinator = _coordinator_with_task(task=task, queue=queue)

    result = coordinator.mark_dead_letter(
        tenant_id=tenant_id,
        task_id=task.id,
        reason="retry budget exhausted",
    )

    assert result.ok is True
    assert result.task_id == task.id
    assert result.state == ExecutionTaskState.DEAD_LETTERED.value
    assert task.status == ExecutionTaskState.DEAD_LETTERED.value
    queue.move_to_dead_letter.assert_called_once_with(
        tenant_id=tenant_id,
        task_id=task.id,
        reason="retry budget exhausted",
    )

    coordinator._governance.append.assert_called_once()
    governance_event = coordinator._governance.append.call_args.args[0]
    assert governance_event.tenant_id == tenant_id
    assert governance_event.mission_id == task.mission_id
    assert governance_event.event_type == "dead_letter"
    assert governance_event.actor == "execution_coordinator"
    assert governance_event.decision == "retry budget exhausted"
    assert governance_event.payload_json == {"task_id": str(task.id)}
    assert coordinator._session.flush.call_count == 2
