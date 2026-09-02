"""Mission status rollup after graph tasks terminalize."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from backend.domain.enums import ExecutionTaskState, MissionState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.services.worker_runtime_service import WorkerRuntimeService


def _task(
    *,
    mission_id: uuid.UUID,
    tenant_id: str,
    status: str,
    action: str | None = None,
    output: dict | None = None,
) -> ExecutionTask:
    metadata: dict = {}
    if action is not None:
        metadata["tool_invocation"] = {"action": action, "input": {}, "schema_version": 1}
    if output is not None:
        metadata["output"] = output
    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=mission_id,
        title="t",
        description="d",
        status=status,
        metadata_json=metadata,
    )
    task.id = uuid.uuid4()
    return task


def test_rollup_marks_mission_completed_when_all_tasks_done() -> None:
    tenant_id = "tenant-1"
    mission_id = uuid.uuid4()
    mission = Mission(
        tenant_id=tenant_id,
        objective="research Absolute Janitorial",
        status=MissionState.PLANNED.value,
        metadata_json={},
    )
    mission.id = mission_id
    tasks = [
        _task(mission_id=mission_id, tenant_id=tenant_id, status=ExecutionTaskState.COMPLETED.value),
        _task(mission_id=mission_id, tenant_id=tenant_id, status=ExecutionTaskState.COMPLETED.value),
    ]
    session = MagicMock()
    queue = MagicMock()
    service = WorkerRuntimeService(session, queue)
    service._tasks.list_for_mission = MagicMock(return_value=tasks)  # type: ignore[method-assign]
    service._audit.append = MagicMock()  # type: ignore[method-assign]
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission
    with patch(
        "backend.services.worker_runtime_service.MissionRepository",
        return_value=repo,
    ):
        service._maybe_rollup_mission_status(task=tasks[0], worker_id="worker-1")
    assert mission.status == MissionState.COMPLETED.value


def test_rollup_marks_running_when_siblings_open() -> None:
    tenant_id = "tenant-1"
    mission_id = uuid.uuid4()
    mission = Mission(
        tenant_id=tenant_id,
        objective="research",
        status=MissionState.PLANNED.value,
        metadata_json={},
    )
    mission.id = mission_id
    done = _task(mission_id=mission_id, tenant_id=tenant_id, status=ExecutionTaskState.COMPLETED.value)
    open_task = _task(mission_id=mission_id, tenant_id=tenant_id, status=ExecutionTaskState.QUEUED.value)
    service = WorkerRuntimeService(MagicMock(), MagicMock())
    service._tasks.list_for_mission = MagicMock(return_value=[done, open_task])  # type: ignore[method-assign]
    service._audit.append = MagicMock()  # type: ignore[method-assign]
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission
    with patch(
        "backend.services.worker_runtime_service.MissionRepository",
        return_value=repo,
    ):
        service._maybe_rollup_mission_status(task=done, worker_id="worker-1")
    assert mission.status == MissionState.RUNNING.value


def test_rollup_marks_mission_failed_when_all_tasks_terminal_and_one_failed() -> None:
    tenant_id = "tenant-1"
    mission_id = uuid.uuid4()
    mission = Mission(
        tenant_id=tenant_id,
        objective="research",
        status=MissionState.RUNNING.value,
        metadata_json={},
    )
    mission.id = mission_id
    completed = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status=ExecutionTaskState.COMPLETED.value,
    )
    failed = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status=ExecutionTaskState.FAILED.value,
    )
    service = WorkerRuntimeService(MagicMock(), MagicMock())
    service._tasks.list_for_mission = MagicMock(return_value=[completed, failed])  # type: ignore[method-assign]
    service._audit.append = MagicMock()  # type: ignore[method-assign]
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission
    with patch(
        "backend.services.worker_runtime_service.MissionRepository",
        return_value=repo,
    ):
        service._maybe_rollup_mission_status(task=failed, worker_id="worker-1")

    assert mission.status == MissionState.FAILED.value


def test_rollup_fails_when_observe_accept_unmet() -> None:
    tenant_id = "tenant-1"
    mission_id = uuid.uuid4()
    mission = Mission(
        tenant_id=tenant_id,
        objective="return contact info for at least five",
        status=MissionState.RUNNING.value,
        metadata_json={},
    )
    mission.id = mission_id
    observe = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status=ExecutionTaskState.COMPLETED.value,
        action="research.observe_contacts",
        output={"accept_met": False, "observed_count": 0, "requested_quantity": 5},
    )
    discover = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status=ExecutionTaskState.COMPLETED.value,
        action="web.research",
    )
    service = WorkerRuntimeService(MagicMock(), MagicMock())
    service._tasks.list_for_mission = MagicMock(return_value=[discover, observe])  # type: ignore[method-assign]
    service._audit.append = MagicMock()  # type: ignore[method-assign]
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission
    with patch(
        "backend.services.worker_runtime_service.MissionRepository",
        return_value=repo,
    ):
        service._maybe_rollup_mission_status(task=observe, worker_id="worker-1")
    assert mission.status == MissionState.FAILED.value


def test_rollup_completes_when_observe_accept_met() -> None:
    tenant_id = "tenant-1"
    mission_id = uuid.uuid4()
    mission = Mission(
        tenant_id=tenant_id,
        objective="return contact info for at least five",
        status=MissionState.RUNNING.value,
        metadata_json={},
    )
    mission.id = mission_id
    observe = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status=ExecutionTaskState.COMPLETED.value,
        action="research.observe_contacts",
        output={"accept_met": True, "observed_count": 5, "requested_quantity": 5},
    )
    service = WorkerRuntimeService(MagicMock(), MagicMock())
    service._tasks.list_for_mission = MagicMock(return_value=[observe])  # type: ignore[method-assign]
    service._audit.append = MagicMock()  # type: ignore[method-assign]
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission
    with patch(
        "backend.services.worker_runtime_service.MissionRepository",
        return_value=repo,
    ):
        service._maybe_rollup_mission_status(task=observe, worker_id="worker-1")
    assert mission.status == MissionState.COMPLETED.value
