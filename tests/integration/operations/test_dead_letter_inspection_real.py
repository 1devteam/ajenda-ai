from __future__ import annotations

import uuid

import pytest

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.services.operations_service import OperationsService

pytestmark = pytest.mark.integration


def _create_tenant(pg_session, tenant_id: str) -> Tenant:
    tenant = Tenant(
        id=uuid.UUID(tenant_id),
        name=f"Tenant-{tenant_id[:8]}",
        slug=f"tenant-{tenant_id[:8]}",
        plan="free",
    )
    pg_session.add(tenant)
    pg_session.flush()
    return tenant


def _create_task(pg_session, tenant_id: str, *, status: ExecutionTaskState) -> ExecutionTask:
    mission = Mission(tenant_id=tenant_id, objective="dead letter mission", status="running")
    pg_session.add(mission)
    pg_session.flush()
    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=mission.id,
        title=f"{status.value} task",
        description=f"{status.value} task",
        status=status.value,
        metadata_json={},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    pg_session.add(task)
    pg_session.flush()
    return task


def test_dead_letter_inspection_returns_only_requested_tenant_rows(pg_session, queue_adapter) -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    _create_tenant(pg_session, tenant_a)
    _create_tenant(pg_session, tenant_b)
    task_a = _create_task(pg_session, tenant_a, status=ExecutionTaskState.DEAD_LETTERED)
    _create_task(pg_session, tenant_b, status=ExecutionTaskState.DEAD_LETTERED)
    pg_session.flush()

    rows = OperationsService(pg_session, queue_adapter).inspect_dead_letter(tenant_id=tenant_a)

    assert len(rows) == 1
    assert rows[0]["task_id"] == str(task_a.id)
    assert rows[0]["mission_id"] == str(task_a.mission_id)
    assert rows[0]["status"] == ExecutionTaskState.DEAD_LETTERED.value


def test_dead_letter_inspection_excludes_non_dead_letter_rows_for_same_tenant(pg_session, queue_adapter) -> None:
    tenant_id = str(uuid.uuid4())
    _create_tenant(pg_session, tenant_id)
    dead_letter_task = _create_task(pg_session, tenant_id, status=ExecutionTaskState.DEAD_LETTERED)
    _create_task(pg_session, tenant_id, status=ExecutionTaskState.COMPLETED)
    _create_task(pg_session, tenant_id, status=ExecutionTaskState.QUEUED)
    _create_task(pg_session, tenant_id, status=ExecutionTaskState.FAILED)
    pg_session.flush()

    rows = OperationsService(pg_session, queue_adapter).inspect_dead_letter(tenant_id=tenant_id)

    assert rows == [
        {
            "task_id": str(dead_letter_task.id),
            "mission_id": str(dead_letter_task.mission_id),
            "status": ExecutionTaskState.DEAD_LETTERED.value,
        }
    ]
