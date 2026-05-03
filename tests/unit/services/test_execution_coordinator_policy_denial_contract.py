from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.domain.enums import ExecutionTaskState
from backend.services.execution_coordinator import ExecutionCoordinator


def _denied_decision() -> SimpleNamespace:
    return SimpleNamespace(
        execution_allowed=False,
        mode="MAINTENANCE",
        reason="runtime governor denied execution",
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
    )


def _coordinator_with_denied_runtime(*, task: SimpleNamespace, queue: MagicMock | None = None) -> ExecutionCoordinator:
    session = MagicMock()
    queue = queue or MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()
    coordinator._tasks.get.return_value = task
    coordinator._governor = MagicMock()
    coordinator._governor.evaluate.return_value = _denied_decision()
    coordinator._policy = MagicMock()
    coordinator._governance = MagicMock()
    coordinator._audit = MagicMock()
    return coordinator


def test_queue_task_runtime_denial_returns_blocked_result_without_enqueueing() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)
    queue = MagicMock()
    coordinator = _coordinator_with_denied_runtime(task=task, queue=queue)

    result = coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    assert result.ok is False
    assert result.task_id == task.id
    assert result.state == ExecutionTaskState.PLANNED.value
    assert result.reason == "runtime governor denied execution"
    assert task.status == ExecutionTaskState.PLANNED.value
    queue.enqueue_task.assert_not_called()


def test_queue_task_runtime_denial_emits_governance_evidence() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)
    coordinator = _coordinator_with_denied_runtime(task=task)

    coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    coordinator._governance.append.assert_called_once()
    governance_event = coordinator._governance.append.call_args.args[0]
    assert governance_event.tenant_id == tenant_id
    assert governance_event.mission_id == task.mission_id
    assert governance_event.event_type == "dispatch_denied"
    assert governance_event.actor == "runtime_governor"
    assert governance_event.decision == "runtime governor denied execution"
    assert governance_event.payload_json == {"task_id": str(task.id)}


def test_queue_task_runtime_denial_flushes_governance_evidence() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)
    coordinator = _coordinator_with_denied_runtime(task=task)

    coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    coordinator._session.flush.assert_called_once()


def test_queue_task_runtime_denial_does_not_call_policy_or_audit_paths() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)
    coordinator = _coordinator_with_denied_runtime(task=task)

    coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    coordinator._policy.evaluate_task.assert_not_called()
    coordinator._audit.append.assert_not_called()
