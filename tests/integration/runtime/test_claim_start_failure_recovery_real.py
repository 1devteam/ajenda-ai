from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueOperationResult
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.runtime_maintainer import RuntimeMaintainer
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.worker_loop import WorkerLoop

pytestmark = pytest.mark.integration


def test_claim_start_heartbeat_failure_remains_recoverable(
    pg_engine,
    queue_adapter,
    redis_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "claim-start-failure-worker"
    recovery_worker_id = "claim-start-recovery-worker"

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
            name="Claim Start Failure Tenant",
            slug=f"claim-start-{tenant_id[:8]}",
            plan="free",
        )
        setup_session.add(tenant)

        mission = Mission(
            tenant_id=tenant_id,
            objective="claim/start failure recovery proof",
            status="running",
        )
        setup_session.add(mission)
        setup_session.flush()

        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="claim start failure task",
            description="Task proves failed claim/start remains recoverable",
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
        setup_session.commit()
    finally:
        setup_session.close()

    def reject_heartbeat(*args: object, **kwargs: object) -> QueueOperationResult:
        return QueueOperationResult(ok=False, reason="redis heartbeat unavailable during claim start")

    monkeypatch.setattr(queue_adapter, "heartbeat", reject_heartbeat)

    loop = WorkerLoop(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
        poll_interval_seconds=0.01,
    )

    assert loop._claim_and_start_task() is None

    verify_claim_session = session_factory()
    try:
        claimed_task = verify_claim_session.get(ExecutionTask, task_id)
        assert claimed_task is not None
        assert claimed_task.status == ExecutionTaskState.CLAIMED.value

        lease = verify_claim_session.scalars(
            select(WorkerLease).where(
                WorkerLease.tenant_id == tenant_id,
                WorkerLease.task_id == task_id,
                WorkerLease.holder_identity == worker_id,
            )
        ).one()

        assert lease.status == WorkerLeaseState.CLAIMED.value
        assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 1
        assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is not None

        lease.heartbeat_at = datetime.now(UTC) - timedelta(seconds=120)
        verify_claim_session.commit()
        lease_id = lease.id
    finally:
        verify_claim_session.close()

    recovery_session = session_factory()
    try:
        summary = RuntimeMaintainer(
            session=recovery_session,
            queue=queue_adapter,
            expiry_seconds=30,
            max_retries=3,
        ).recover_expired_leases()
        assert summary.expired_lease_count >= 1
        assert summary.requeued_task_count >= 1
    finally:
        recovery_session.close()

    reclaim_session = session_factory()
    try:
        recovered_task = reclaim_session.get(ExecutionTask, task_id)
        recovered_lease = reclaim_session.get(WorkerLease, lease_id)

        assert recovered_task is not None
        assert recovered_task.retry_count == 1
        assert recovered_lease is not None
        assert recovered_lease.status == WorkerLeaseState.EXPIRED.value
        assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
        assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None

        reclaimed = WorkerRuntimeService(reclaim_session, queue_adapter).claim_next_task(
            tenant_id=tenant_id,
            worker_id=recovery_worker_id,
        )

        assert reclaimed is not None
        assert reclaimed.id == task_id
    finally:
        reclaim_session.close()
