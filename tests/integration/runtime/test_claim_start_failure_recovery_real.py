from __future__ import annotations

import uuid
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class QueuedRuntimeTask:
    tenant_id: str
    task_id: uuid.UUID
    session_factory: sessionmaker


def _queue_runtime_task(pg_engine, queue_adapter, *, title: str) -> QueuedRuntimeTask:
    tenant_id = str(uuid.uuid4())
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
            name=f"{title} Tenant",
            slug=f"claim-start-{tenant_id[:8]}",
            plan="free",
        )
        setup_session.add(tenant)

        mission = Mission(
            tenant_id=tenant_id,
            objective=title,
            status="running",
        )
        setup_session.add(mission)
        setup_session.flush()

        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title=title,
            description="Task proves claim/start crash recovery",
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

    return QueuedRuntimeTask(tenant_id=tenant_id, task_id=task_id, session_factory=session_factory)


def _active_lease_count(session, *, tenant_id: str, task_id: uuid.UUID) -> int:
    return len(
        session.scalars(
            select(WorkerLease).where(
                WorkerLease.tenant_id == tenant_id,
                WorkerLease.task_id == task_id,
                WorkerLease.status == WorkerLeaseState.ACTIVE.value,
            )
        ).all()
    )


def _expire_lease(session, *, lease_id: uuid.UUID) -> None:
    lease = session.get(WorkerLease, lease_id)
    assert lease is not None
    lease.heartbeat_at = datetime.now(UTC) - timedelta(seconds=120)
    session.commit()


def _recover_expired(session_factory: sessionmaker, queue_adapter) -> None:
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


def _assert_recoverable_and_reclaim_once(
    queued: QueuedRuntimeTask,
    queue_adapter,
    redis_client,
    *,
    original_lease_id: uuid.UUID,
    recovery_worker_id: str,
) -> None:
    reclaim_session = queued.session_factory()
    try:
        recovered_task = reclaim_session.get(ExecutionTask, queued.task_id)
        recovered_lease = reclaim_session.get(WorkerLease, original_lease_id)

        assert recovered_task is not None
        assert recovered_task.status in {
            ExecutionTaskState.QUEUED.value,
            ExecutionTaskState.RUNNING.value,
            ExecutionTaskState.COMPLETED.value,
            ExecutionTaskState.FAILED.value,
        }
        assert recovered_task.retry_count == 1
        assert recovered_lease is not None
        assert recovered_lease.status == WorkerLeaseState.EXPIRED.value
        assert redis_client.llen(f"ajenda:queue:{queued.tenant_id}:processing") == 0
        assert redis_client.get(f"ajenda:queue:{queued.tenant_id}:lease:{queued.task_id}") is None
        assert (
            _active_lease_count(
                reclaim_session,
                tenant_id=queued.tenant_id,
                task_id=queued.task_id,
            )
            <= 1
        )

        reclaimed = WorkerRuntimeService(reclaim_session, queue_adapter).claim_next_task(
            tenant_id=queued.tenant_id,
            worker_id=recovery_worker_id,
        )

        assert reclaimed is not None
        assert reclaimed.id == queued.task_id
        assert (
            _active_lease_count(
                reclaim_session,
                tenant_id=queued.tenant_id,
                task_id=queued.task_id,
            )
            <= 1
        )
    finally:
        reclaim_session.close()


def test_claim_start_heartbeat_failure_remains_recoverable(
    pg_engine,
    queue_adapter,
    redis_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued = _queue_runtime_task(pg_engine, queue_adapter, title="claim start heartbeat failure")
    worker_id = "claim-start-failure-worker"

    def reject_heartbeat(*args: object, **kwargs: object) -> QueueOperationResult:
        return QueueOperationResult(ok=False, reason="redis heartbeat unavailable during claim start")

    monkeypatch.setattr(queue_adapter, "heartbeat", reject_heartbeat)

    loop = WorkerLoop(
        session_factory=queued.session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=queued.tenant_id,
        poll_interval_seconds=0.01,
    )

    assert loop._claim_and_start_task() is None

    verify_claim_session = queued.session_factory()
    try:
        claimed_task = verify_claim_session.get(ExecutionTask, queued.task_id)
        assert claimed_task is not None
        assert claimed_task.status == ExecutionTaskState.CLAIMED.value

        lease = verify_claim_session.scalars(
            select(WorkerLease).where(
                WorkerLease.tenant_id == queued.tenant_id,
                WorkerLease.task_id == queued.task_id,
                WorkerLease.holder_identity == worker_id,
            )
        ).one()

        assert lease.status == WorkerLeaseState.CLAIMED.value
        assert redis_client.llen(f"ajenda:queue:{queued.tenant_id}:processing") == 1
        assert redis_client.get(f"ajenda:queue:{queued.tenant_id}:lease:{queued.task_id}") is not None
        lease_id = lease.id
        _expire_lease(verify_claim_session, lease_id=lease_id)
    finally:
        verify_claim_session.close()

    _recover_expired(queued.session_factory, queue_adapter)
    _assert_recoverable_and_reclaim_once(
        queued,
        queue_adapter,
        redis_client,
        original_lease_id=lease_id,
        recovery_worker_id="claim-start-recovery-worker",
    )


def test_crash_after_claim_before_start_remains_recoverable(pg_engine, queue_adapter, redis_client) -> None:
    queued = _queue_runtime_task(pg_engine, queue_adapter, title="crash after claim before start")
    worker_id = "claim-crash-worker"

    claim_session = queued.session_factory()
    try:
        claimed = WorkerRuntimeService(claim_session, queue_adapter).claim_next_task(
            tenant_id=queued.tenant_id,
            worker_id=worker_id,
        )
        assert claimed is not None
        lease_id = uuid.UUID(claimed.metadata_json["worker_lease_id"])
    finally:
        claim_session.close()

    verify_session = queued.session_factory()
    try:
        task = verify_session.get(ExecutionTask, queued.task_id)
        lease = verify_session.get(WorkerLease, lease_id)
        assert task is not None
        assert task.status == ExecutionTaskState.CLAIMED.value
        assert lease is not None
        assert lease.status == WorkerLeaseState.CLAIMED.value
        _expire_lease(verify_session, lease_id=lease_id)
    finally:
        verify_session.close()

    _recover_expired(queued.session_factory, queue_adapter)
    _assert_recoverable_and_reclaim_once(
        queued,
        queue_adapter,
        redis_client,
        original_lease_id=lease_id,
        recovery_worker_id="claim-crash-recovery-worker",
    )


def test_crash_after_heartbeat_before_start_resolves_active_claimed_mismatch(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    queued = _queue_runtime_task(pg_engine, queue_adapter, title="crash after heartbeat before start")
    worker_id = "heartbeat-crash-worker"

    claim_session = queued.session_factory()
    try:
        runtime = WorkerRuntimeService(claim_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=queued.tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(claimed.metadata_json["worker_lease_id"])
        runtime.heartbeat(tenant_id=queued.tenant_id, lease_id=lease_id, worker_id=worker_id)
    finally:
        claim_session.close()

    verify_session = queued.session_factory()
    try:
        task = verify_session.get(ExecutionTask, queued.task_id)
        lease = verify_session.get(WorkerLease, lease_id)
        assert task is not None
        assert task.status == ExecutionTaskState.CLAIMED.value
        assert lease is not None
        assert lease.status == WorkerLeaseState.ACTIVE.value
        assert _active_lease_count(verify_session, tenant_id=queued.tenant_id, task_id=queued.task_id) <= 1
        _expire_lease(verify_session, lease_id=lease_id)
    finally:
        verify_session.close()

    _recover_expired(queued.session_factory, queue_adapter)
    _assert_recoverable_and_reclaim_once(
        queued,
        queue_adapter,
        redis_client,
        original_lease_id=lease_id,
        recovery_worker_id="heartbeat-crash-recovery-worker",
    )


def test_crash_after_start_execution_before_dispatch_does_not_duplicate_active_execution(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    queued = _queue_runtime_task(pg_engine, queue_adapter, title="crash after start execution")
    worker_id = "start-crash-worker"

    start_session = queued.session_factory()
    try:
        runtime = WorkerRuntimeService(start_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=queued.tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(claimed.metadata_json["worker_lease_id"])
        runtime.heartbeat(tenant_id=queued.tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=queued.tenant_id, lease_id=lease_id, worker_id=worker_id)
    finally:
        start_session.close()

    verify_session = queued.session_factory()
    try:
        task = verify_session.get(ExecutionTask, queued.task_id)
        lease = verify_session.get(WorkerLease, lease_id)
        assert task is not None
        assert task.status == ExecutionTaskState.RUNNING.value
        assert lease is not None
        assert lease.status == WorkerLeaseState.ACTIVE.value
        assert _active_lease_count(verify_session, tenant_id=queued.tenant_id, task_id=queued.task_id) <= 1
        _expire_lease(verify_session, lease_id=lease_id)
    finally:
        verify_session.close()

    _recover_expired(queued.session_factory, queue_adapter)
    _assert_recoverable_and_reclaim_once(
        queued,
        queue_adapter,
        redis_client,
        original_lease_id=lease_id,
        recovery_worker_id="start-crash-recovery-worker",
    )
