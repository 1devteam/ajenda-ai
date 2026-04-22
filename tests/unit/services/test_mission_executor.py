from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from backend.services.execution_coordinator import CoordinationResult
from backend.services.mission_executor import MissionExecutor


def _make_task(*, tenant_id: str, mission_id: uuid.UUID) -> MagicMock:
    task = MagicMock()
    task.id = uuid.uuid4()
    task.tenant_id = tenant_id
    task.mission_id = mission_id
    return task


def test_queue_all_planned_tasks_separates_queued_pending_review_and_denied() -> None:
    tenant_id = str(uuid.uuid4())
    other_tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()

    queued_task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    pending_review_task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    denied_task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    foreign_task = _make_task(tenant_id=other_tenant_id, mission_id=mission_id)

    session = MagicMock()
    coordinator = MagicMock()
    executor = MissionExecutor(session, coordinator)

    executor._tasks = MagicMock()
    executor._tasks.list_for_mission.return_value = [
        queued_task,
        pending_review_task,
        denied_task,
        foreign_task,
    ]

    coordinator.queue_task.side_effect = [
        CoordinationResult(ok=True, task_id=queued_task.id, state="queued"),
        CoordinationResult(
            ok=False,
            task_id=pending_review_task.id,
            state="pending_review",
            reason="human review required",
        ),
        CoordinationResult(
            ok=False,
            task_id=denied_task.id,
            state="blocked",
            reason="runtime governor denied execution",
        ),
    ]

    summary = executor.queue_all_planned_tasks(tenant_id=tenant_id, mission_id=mission_id)

    assert summary.queued_task_ids == [queued_task.id]
    assert summary.pending_review_task_ids == [pending_review_task.id]
    assert len(summary.denied_tasks) == 1
    assert summary.denied_tasks[0].task_id == denied_task.id
    assert summary.denied_tasks[0].state == "blocked"
    assert summary.denied_tasks[0].reason == "runtime governor denied execution"
    coordinator.queue_task.assert_any_call(tenant_id=tenant_id, task_id=queued_task.id)
    coordinator.queue_task.assert_any_call(tenant_id=tenant_id, task_id=pending_review_task.id)
    coordinator.queue_task.assert_any_call(tenant_id=tenant_id, task_id=denied_task.id)
    assert coordinator.queue_task.call_count == 3
