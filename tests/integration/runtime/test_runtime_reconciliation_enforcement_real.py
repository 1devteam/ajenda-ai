from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.runtime_maintainer import RuntimeMaintainer

pytestmark = pytest.mark.integration


def _create_queued_task(pg_session, queue_adapter) -> tuple[str, uuid.UUID]:
    tenant_id = str(uuid.uuid4())

    tenant = Tenant(
        id=uuid.UUID(tenant_id),
        name="Runtime Reconciliation Enforcement Tenant",
        slug=f"runtime-reconcile-{tenant_id[:8]}",
        plan="free",
    )
    pg_session.add(tenant)

    mission = Mission(
        tenant_id=tenant_id,
        objective="runtime reconciliation enforcement",
        status="running",
    )
    pg_session.add(mission)
    pg_session.flush()

    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=mission.id,
        title="runtime reconciliation task",
        description="Task used to prove runtime reconciliation enforcement",
        status=ExecutionTaskState.PLANNED.value,
        metadata_json={},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    pg_session.add(task)
    pg_session.flush()

    QuotaEnforcementService(pg_session).check_and_record_task_creation(uuid.UUID(tenant_id))
    queued = ExecutionCoordinator(pg_session, queue_adapter).queue_task(
        tenant_id=tenant_id,
        task_id=task.id,
    )
    assert queued.ok is True
    pg_session.commit()

    return tenant_id, task.id


def _stale_time() -> datetime:
    return datetime.now(UTC) - timedelta(seconds=120)


def test_recovery_expires_duplicate_active_leases_for_same_task(pg_session, queue_adapter, redis_client) -> None:
    tenant_id, task_id = _create_queued_task(pg_session, queue_adapter)

    task = pg_session.get(ExecutionTask, task_id)
    assert task is not None
    task.status = ExecutionTaskState.RUNNING.value

    first = WorkerLease(
        tenant_id=tenant_id,
        task_id=task_id,
        status=WorkerLeaseState.ACTIVE.value,
        holder_identity="duplicate-worker-1",
        heartbeat_at=_stale_time(),
    )
    second = WorkerLease(
        tenant_id=tenant_id,
        task_id=task_id,
        status=WorkerLeaseState.ACTIVE.value,
        holder_identity="duplicate-worker-2",
        heartbeat_at=_stale_time(),
    )
    pg_session.add_all([first, second])
    pg_session.commit()

    summary = RuntimeMaintainer(pg_session, queue_adapter, expiry_seconds=30).recover_expired_leases()

    leases = pg_session.scalars(
        select(WorkerLease).where(
            WorkerLease.tenant_id == tenant_id,
            WorkerLease.task_id == task_id,
        )
    ).all()

    active_or_claimed = [
        lease for lease in leases if lease.status in {WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value}
    ]

    recovered_task = pg_session.get(ExecutionTask, task_id)
    assert recovered_task is not None
    assert active_or_claimed == []
    assert recovered_task.status in {
        ExecutionTaskState.QUEUED.value,
        ExecutionTaskState.DEAD_LETTERED.value,
    }
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
    assert summary.expired_lease_count >= 2


def test_recovery_requeues_running_task_without_valid_active_lease(pg_session, queue_adapter) -> None:
    tenant_id, task_id = _create_queued_task(pg_session, queue_adapter)

    task = pg_session.get(ExecutionTask, task_id)
    assert task is not None
    task.status = ExecutionTaskState.RUNNING.value
    pg_session.commit()

    summary = RuntimeMaintainer(pg_session, queue_adapter, expiry_seconds=30).recover_expired_leases()

    recovered_task = pg_session.get(ExecutionTask, task_id)
    assert recovered_task is not None
    assert recovered_task.status == ExecutionTaskState.QUEUED.value
    assert summary.requeued_task_count >= 1


def test_recovery_releases_terminal_task_active_lease(pg_session, queue_adapter, redis_client) -> None:
    tenant_id, task_id = _create_queued_task(pg_session, queue_adapter)

    task = pg_session.get(ExecutionTask, task_id)
    assert task is not None
    task.status = ExecutionTaskState.COMPLETED.value

    lease = WorkerLease(
        tenant_id=tenant_id,
        task_id=task_id,
        status=WorkerLeaseState.ACTIVE.value,
        holder_identity="terminal-worker",
        heartbeat_at=_stale_time(),
    )
    pg_session.add(lease)
    pg_session.commit()

    RuntimeMaintainer(pg_session, queue_adapter, expiry_seconds=30).recover_expired_leases()

    recovered_lease = pg_session.get(WorkerLease, lease.id)
    recovered_task = pg_session.get(ExecutionTask, task_id)

    assert recovered_task is not None
    assert recovered_task.status == ExecutionTaskState.COMPLETED.value
    assert recovered_lease is not None
    assert recovered_lease.status in {
        WorkerLeaseState.RELEASED.value,
        WorkerLeaseState.EXPIRED.value,
    }
    assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None


def test_recovery_requeues_running_task_with_only_expired_lease(pg_session, queue_adapter) -> None:
    tenant_id, task_id = _create_queued_task(pg_session, queue_adapter)

    task = pg_session.get(ExecutionTask, task_id)
    assert task is not None
    task.status = ExecutionTaskState.RUNNING.value

    lease = WorkerLease(
        tenant_id=tenant_id,
        task_id=task_id,
        status=WorkerLeaseState.EXPIRED.value,
        holder_identity="expired-worker",
        heartbeat_at=_stale_time(),
    )
    pg_session.add(lease)
    pg_session.commit()

    summary = RuntimeMaintainer(pg_session, queue_adapter, expiry_seconds=30).recover_expired_leases()

    recovered_task = pg_session.get(ExecutionTask, task_id)
    assert recovered_task is not None
    assert recovered_task.status == ExecutionTaskState.QUEUED.value
    assert summary.requeued_task_count >= 1
    assert summary.mismatched_state_count >= 1


def test_recovery_releases_fresh_terminal_task_active_lease(pg_session, queue_adapter, redis_client) -> None:
    tenant_id, task_id = _create_queued_task(pg_session, queue_adapter)

    task = pg_session.get(ExecutionTask, task_id)
    assert task is not None
    task.status = ExecutionTaskState.COMPLETED.value

    lease = WorkerLease(
        tenant_id=tenant_id,
        task_id=task_id,
        status=WorkerLeaseState.ACTIVE.value,
        holder_identity="fresh-terminal-worker",
        heartbeat_at=datetime.now(UTC),
    )
    pg_session.add(lease)
    pg_session.commit()

    RuntimeMaintainer(pg_session, queue_adapter, expiry_seconds=30).recover_expired_leases()

    recovered_task = pg_session.get(ExecutionTask, task_id)
    recovered_lease = pg_session.get(WorkerLease, lease.id)

    assert recovered_task is not None
    assert recovered_task.status == ExecutionTaskState.COMPLETED.value
    assert recovered_lease is not None
    assert recovered_lease.status in {
        WorkerLeaseState.RELEASED.value,
        WorkerLeaseState.EXPIRED.value,
    }
    assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None
