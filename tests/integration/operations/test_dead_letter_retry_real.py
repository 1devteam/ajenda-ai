from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.runtime_queue_dispatch import RuntimeQueueDispatch
from backend.domain.tenant import Tenant
from backend.services.operations_service import OperationsService

pytestmark = pytest.mark.integration


def test_rg_dead_letter_retry_requeues_db_only_dead_letter_task(pg_engine, queue_adapter, redis_client) -> None:
    """A DB-only retry becomes visible in Redis only after a real durable commit.

    The regular pg_session fixture wraps tests in an uncommitted outer transaction.
    Its session.commit() cannot make rows visible to the dispatch callback's
    independent connection, so this proof uses an engine-bound transaction.
    """
    tenant_id = str(uuid.uuid4())
    task_id: uuid.UUID | None = None
    try:
        with Session(pg_engine, expire_on_commit=False) as session:
            tenant = Tenant(id=uuid.UUID(tenant_id), name="Tenant-RG10", slug=f"tenant-{tenant_id[:8]}", plan="free")
            session.add(tenant)
            session.flush()

            mission = Mission(tenant_id=tenant_id, objective="dead-letter retry", status="running")
            session.add(mission)
            session.flush()

            task = ExecutionTask(
                tenant_id=tenant_id,
                mission_id=mission.id,
                title="dead-letter task",
                description="should requeue from DB dead-letter truth",
                status=ExecutionTaskState.DEAD_LETTERED.value,
                metadata_json={"attempt": 1},
            )
            session.add(task)
            session.flush()
            task_id = task.id

            result = OperationsService(session, queue_adapter).retry_dead_letter(tenant_id=tenant_id, task_id=task.id)

            assert result == {"task_id": str(task.id), "status": ExecutionTaskState.QUEUED.value}
            assert task.status == ExecutionTaskState.QUEUED.value
            dispatch = session.query(RuntimeQueueDispatch).filter_by(task_id=task.id).one()
            assert dispatch.status == "pending"
            assert redis_client.zcard(f"ajenda:queue:{tenant_id}:v2:pending-order") == 0

            # The after_commit callback uses a separate database connection.
            # Only a real outer commit makes the dispatch visible for publication.
            session.commit()

        with Session(pg_engine) as verified:
            persisted_task = verified.get(ExecutionTask, task_id)
            persisted_dispatch = verified.query(RuntimeQueueDispatch).filter_by(task_id=task_id).one()
            assert persisted_task is not None
            assert persisted_task.status == ExecutionTaskState.QUEUED.value
            assert persisted_dispatch.status == "published"
            assert persisted_dispatch.published_at is not None
        assert redis_client.zcard(f"ajenda:queue:{tenant_id}:v2:pending-order") == 1
    finally:
        # This test intentionally commits. Remove its isolated tenant's records
        # rather than leaving durable fixtures in the session-scoped database.
        with Session(pg_engine) as cleanup:
            cleanup.execute(delete(RuntimeQueueDispatch).where(RuntimeQueueDispatch.tenant_id == tenant_id))
            cleanup.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
            cleanup.execute(delete(ExecutionTask).where(ExecutionTask.tenant_id == tenant_id))
            cleanup.execute(delete(Mission).where(Mission.tenant_id == tenant_id))
            cleanup.execute(delete(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
            cleanup.commit()
