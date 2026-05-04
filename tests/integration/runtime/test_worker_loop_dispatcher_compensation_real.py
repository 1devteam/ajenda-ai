from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers import worker_loop
from backend.workers.worker_loop import WorkerLoop

pytestmark = pytest.mark.integration


def test_worker_loop_compensates_when_dispatcher_raises_against_real_runtime(
    pg_engine,
    queue_adapter,
    redis_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-loop-dispatcher-compensation"
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
            name="Worker Loop Compensation Tenant",
            slug=f"worker-loop-{tenant_id[:8]}",
            plan="free",
        )
        setup_session.add(tenant)
        mission = Mission(tenant_id=tenant_id, objective="Worker loop compensation mission", status="running")
        setup_session.add(mission)
        setup_session.flush()

        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="Worker loop compensation task",
            description="Task proves worker loop dispatcher compensation",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={},
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

    class RaisingDispatcher:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["worker_id"] == worker_id
            assert kwargs["tenant_id"] == tenant_id

        def execute(self, *, task_id: uuid.UUID, lease_id: uuid.UUID) -> None:
            raise RuntimeError("dispatcher crashed after worker claim")

    monkeypatch.setattr(worker_loop, "TaskDispatcher", RaisingDispatcher)

    loop = WorkerLoop(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
        poll_interval_seconds=0.01,
    )
    loop._run_claimed_task(task_id=task_id, lease_id=lease_id)

    verify_session = session_factory()
    try:
        final_task = verify_session.get(ExecutionTask, task_id)
        final_lease = verify_session.get(WorkerLease, lease_id)

        assert final_task is not None
        assert final_task.status == ExecutionTaskState.FAILED.value
        assert final_lease is not None
        assert final_lease.status == WorkerLeaseState.RELEASED.value
        assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
        assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None
    finally:
        verify_session.close()
