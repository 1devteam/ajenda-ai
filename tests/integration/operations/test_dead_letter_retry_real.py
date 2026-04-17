from __future__ import annotations

import uuid

import pytest

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.services.operations_service import OperationsService

pytestmark = pytest.mark.integration


def test_rg_dead_letter_retry_illegal_transition_keeps_state(pg_session, queue_adapter, redis_client) -> None:
    tenant_id = str(uuid.uuid4())
    tenant = Tenant(id=uuid.UUID(tenant_id), name="Tenant-RG10", slug=f"tenant-{tenant_id[:8]}", plan="free")
    pg_session.add(tenant)
    pg_session.flush()

    mission = Mission(tenant_id=tenant_id, objective="dead-letter retry", status="running")
    pg_session.add(mission)
    pg_session.flush()

    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=mission.id,
        title="dead-letter task",
        description="should stay dead-lettered",
        status=ExecutionTaskState.DEAD_LETTERED.value,
        metadata_json={"attempt": 1},
    )
    pg_session.add(task)
    pg_session.flush()

    svc = OperationsService(pg_session, queue_adapter)
    with pytest.raises(ValueError, match="Invalid task transition"):
        svc.retry_dead_letter(tenant_id=tenant_id, task_id=task.id)

    pg_session.refresh(task)
    assert task.status == ExecutionTaskState.DEAD_LETTERED.value
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:pending") == 0
