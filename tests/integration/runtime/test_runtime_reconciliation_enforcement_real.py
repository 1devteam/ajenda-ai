from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueMessage
from backend.services.runtime_maintainer import RuntimeMaintainer

pytestmark = pytest.mark.integration


def _session_factory(pg_engine) -> sessionmaker:
    return sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def _tenant_id() -> str:
    return str(uuid.uuid4())


def _create_tenant(session, tenant_id: str) -> None:
    session.add(
        Tenant(
            id=uuid.UUID(tenant_id),
            name=f"Runtime Enforcement {tenant_id[:8]}",
            slug=f"runtime-enforcement-{tenant_id[:8]}",
            plan="free",
        )
    )


def _create_mission(session, tenant_id: str) -> Mission:
    mission = Mission(
        tenant_id=tenant_id,
        objective="Runtime reconciliation enforcement",
        status="running",
    )
    session.add(mission)
    session.flush()
    return mission


def _create_task(session, *, tenant_id: str, mission_id, status: str) -> ExecutionTask:
    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=mission_id,
        title="Runtime reconciliation enforcement task",
        description="Proves stale ownership convergence",
        status=status,
        metadata_json={},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    session.add(task)
    session.flush()
    return task


def _create_lease(
    session,
    *,
    tenant_id: str,
    task_id,
    status: str = WorkerLeaseState.ACTIVE.value,
    heartbeat_age_seconds: int = 120,
    worker_id: str = "runtime-enforcement-worker",
) -> WorkerLease:
    lease = WorkerLease(
        tenant_id=tenant_id,
        task_id=task_id,
        holder_identity=worker_id,
        status=status,
        heartbeat_at=datetime.now(UTC) - timedelta(seconds=heartbeat_age_seconds),
    )
    session.add(lease)
    session.flush()
    return lease


def _prime_processing_payload(queue_adapter, *, tenant_id: str, task: ExecutionTask, worker_id: str) -> None:
    message = QueueMessage(
        tenant_id=tenant_id,
        task_id=task.id,
        mission_id=task.mission_id,
        fleet_id=task.fleet_id,
        branch_id=task.branch_id,
        payload=dict(task.metadata_json),
        enqueued_at=datetime.now(UTC),
    )
    result = queue_adapter.enqueue_task(message)
    assert result.ok is True
    claimed = queue_adapter.claim_task(tenant_id=tenant_id, worker_id=worker_id)
    assert claimed is not None
    assert claimed.task_id == task.id


def test_terminal_task_with_expired_active_lease_expires_ownership_without_requeue(
    pg_engine,
    queue_adapter,
) -> None:
    session_factory = _session_factory(pg_engine)
    tenant_id = _tenant_id()

    session = session_factory()
    try:
        _create_tenant(session, tenant_id)
        mission = _create_mission(session, tenant_id)
        task = _create_task(
            session,
            tenant_id=tenant_id,
            mission_id=mission.id,
            status=ExecutionTaskState.COMPLETED.value,
        )
        lease = _create_lease(
            session,
            tenant_id=tenant_id,
            task_id=task.id,
            status=WorkerLeaseState.ACTIVE.value,
            heartbeat_age_seconds=120,
        )
        session.commit()

        summary = RuntimeMaintainer(
            session=session,
            queue=queue_adapter,
            expiry_seconds=30,
            max_retries=3,
        ).recover_expired_leases()

        session.refresh(task)
        session.refresh(lease)

        assert summary.expired_lease_count == 1
        assert summary.requeued_task_count == 0
        assert summary.dead_lettered_count == 0
        assert task.status == ExecutionTaskState.COMPLETED.value
        assert lease.status == WorkerLeaseState.EXPIRED.value
    finally:
        session.close()


def test_running_task_with_expired_active_lease_and_pending_duplicate_converges_to_single_pending(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    session_factory = _session_factory(pg_engine)
    tenant_id = _tenant_id()

    session = session_factory()
    try:
        _create_tenant(session, tenant_id)
        mission = _create_mission(session, tenant_id)
        task = _create_task(
            session,
            tenant_id=tenant_id,
            mission_id=mission.id,
            status=ExecutionTaskState.RUNNING.value,
        )
        lease = _create_lease(
            session,
            tenant_id=tenant_id,
            task_id=task.id,
            status=WorkerLeaseState.ACTIVE.value,
            heartbeat_age_seconds=120,
        )
        _prime_processing_payload(queue_adapter, tenant_id=tenant_id, task=task, worker_id=lease.holder_identity)

        duplicate = QueueMessage(
            tenant_id=tenant_id,
            task_id=task.id,
            mission_id=task.mission_id,
            fleet_id=task.fleet_id,
            branch_id=task.branch_id,
            payload=dict(task.metadata_json),
            enqueued_at=datetime.now(UTC),
        )
        assert queue_adapter.enqueue_task(duplicate).ok is True
        session.commit()

        summary = RuntimeMaintainer(
            session=session,
            queue=queue_adapter,
            expiry_seconds=30,
            max_retries=3,
        ).recover_expired_leases()

        session.refresh(task)
        session.refresh(lease)

        pending_key = f"ajenda:queue:{tenant_id}:pending"
        processing_key = f"ajenda:queue:{tenant_id}:processing"

        pending_payloads = redis_client.lrange(pending_key, 0, -1)
        processing_payloads = redis_client.lrange(processing_key, 0, -1)

        matching_pending = [payload for payload in pending_payloads if str(task.id) in payload]
        matching_processing = [payload for payload in processing_payloads if str(task.id) in payload]

        assert summary.expired_lease_count == 1
        assert summary.requeued_task_count == 1
        assert summary.dead_lettered_count == 0
        assert task.status == ExecutionTaskState.QUEUED.value
        assert task.retry_count == 1
        assert lease.status == WorkerLeaseState.EXPIRED.value
        assert len(matching_pending) == 1
        assert matching_processing == []
    finally:
        session.close()


def test_running_task_missing_queue_payload_fails_closed_without_state_mutation(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    session_factory = _session_factory(pg_engine)
    tenant_id = _tenant_id()

    session = session_factory()
    try:
        _create_tenant(session, tenant_id)
        mission = _create_mission(session, tenant_id)
        task = _create_task(
            session,
            tenant_id=tenant_id,
            mission_id=mission.id,
            status=ExecutionTaskState.RUNNING.value,
        )
        lease = _create_lease(
            session,
            tenant_id=tenant_id,
            task_id=task.id,
            status=WorkerLeaseState.ACTIVE.value,
            heartbeat_age_seconds=120,
        )
        redis_client.delete(
            f"ajenda:queue:{tenant_id}:pending",
            f"ajenda:queue:{tenant_id}:processing",
            f"ajenda:queue:{tenant_id}:lease:{task.id}",
        )
        session.commit()

        with pytest.raises(RuntimeError, match="task not found in processing or pending queue"):
            RuntimeMaintainer(
                session=session,
                queue=queue_adapter,
                expiry_seconds=30,
                max_retries=3,
            ).recover_expired_leases()

        session.rollback()
        session.refresh(task)
        session.refresh(lease)

        assert task.status == ExecutionTaskState.RUNNING.value
        assert task.retry_count == 0
        assert lease.status == WorkerLeaseState.ACTIVE.value

        lease.status = WorkerLeaseState.EXPIRED.value
        session.commit()
    finally:
        session.close()
