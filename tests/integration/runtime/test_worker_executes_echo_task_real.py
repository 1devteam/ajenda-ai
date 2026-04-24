from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueOperationResult
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher

pytestmark = pytest.mark.integration


def test_worker_executes_echo_task_and_persists_output(pg_engine, queue_adapter, redis_client) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-echo-real"
    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    setup_session = session_factory()
    try:
        tenant = Tenant(
            id=uuid.UUID(tenant_id),
            name="Echo Tenant",
            slug=f"echo-{tenant_id[:8]}",
            plan="free",
        )
        setup_session.add(tenant)
        mission = Mission(tenant_id=tenant_id, objective="Echo mission", status="running")
        setup_session.add(mission)
        setup_session.flush()

        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="Echo task",
            description="Task proves real handler output persistence",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={"task_type": "echo", "input": {"message": "hello"}},
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        setup_session.add(task)
        setup_session.flush()
        task_id = task.id

        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_id))
        queued = ExecutionCoordinator(setup_session, queue_adapter).queue_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )
        assert queued.ok is True

        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup_session.commit()
    finally:
        setup_session.close()

    dispatcher = TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    )
    dispatcher.execute(task_id=task_id, lease_id=lease_id)

    verify_session = session_factory()
    try:
        final_task = verify_session.get(ExecutionTask, task_id)
        final_lease = verify_session.get(WorkerLease, lease_id)
        lineage = verify_session.scalars(
            select(LineageRecord).where(
                LineageRecord.tenant_id == tenant_id,
                LineageRecord.task_id == task_id,
                LineageRecord.worker_lease_id == lease_id,
                LineageRecord.relationship_type == "task_output",
            )
        ).all()

        assert final_task is not None
        assert final_task.status == ExecutionTaskState.COMPLETED.value
        assert final_lease is not None
        assert final_lease.status == WorkerLeaseState.RELEASED.value
        assert len(lineage) == 1
        assert lineage[0].relationship_reason == "echo handler completed"
        assert lineage[0].metadata_json == {
            "handler": "echo",
            "input": {"message": "hello"},
            "output": {"message": "hello"},
            "status": "completed",
        }
        assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
        assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None
    finally:
        verify_session.close()


def test_echo_output_is_not_persisted_when_completion_fails(
    pg_engine,
    queue_adapter,
    redis_client,
    monkeypatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-echo-complete-fails"
    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    setup_session = session_factory()
    try:
        tenant = Tenant(
            id=uuid.UUID(tenant_id),
            name="Echo Failure Tenant",
            slug=f"echo-fail-{tenant_id[:8]}",
            plan="free",
        )
        setup_session.add(tenant)
        mission = Mission(tenant_id=tenant_id, objective="Echo failure mission", status="running")
        setup_session.add(mission)
        setup_session.flush()

        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="Echo failure task",
            description="Task proves output is not persisted before completion",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={"task_type": "echo", "input": {"message": "hello"}},
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        setup_session.add(task)
        setup_session.flush()
        task_id = task.id

        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_id))
        queued = ExecutionCoordinator(setup_session, queue_adapter).queue_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )
        assert queued.ok is True

        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup_session.commit()
    finally:
        setup_session.close()

    def reject_complete_task(*args, **kwargs) -> QueueOperationResult:
        return QueueOperationResult(ok=False, reason="processing payload missing")

    monkeypatch.setattr(queue_adapter, "complete_task", reject_complete_task)

    dispatcher = TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    )
    dispatcher.execute(task_id=task_id, lease_id=lease_id)

    verify_session = session_factory()
    try:
        lineage_count = verify_session.scalar(
            select(func.count())
            .select_from(LineageRecord)
            .where(
                LineageRecord.tenant_id == tenant_id,
                LineageRecord.task_id == task_id,
                LineageRecord.worker_lease_id == lease_id,
                LineageRecord.relationship_type == "task_output",
            )
        )
        final_task = verify_session.get(ExecutionTask, task_id)

        assert lineage_count == 0
        assert final_task is not None
        assert final_task.status != ExecutionTaskState.COMPLETED.value
    finally:
        verify_session.close()
