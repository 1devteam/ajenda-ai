from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.api.routes.observability import _collect_snapshot
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService

pytestmark = pytest.mark.integration


def test_metrics_snapshot_does_not_trigger_runtime_recovery_or_mutate_stale_lease_state(
    pg_engine,
    queue_adapter,
) -> None:
    tenant_id = str(uuid.uuid4())
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    setup_session = session_factory()
    try:
        setup_session.add(
            Tenant(
                id=uuid.UUID(tenant_id),
                name="Metrics Runtime Tenant",
                slug=f"metrics-runtime-{tenant_id[:8]}",
                plan="free",
            )
        )
        mission = Mission(tenant_id=tenant_id, objective="metrics non-mutating", status="running")
        setup_session.add(mission)
        setup_session.flush()

        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="stale claimed task",
            description="prove metrics endpoint does not recover stale work",
            status=ExecutionTaskState.CLAIMED.value,
            metadata_json={},
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        setup_session.add(task)
        setup_session.flush()

        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_id))
        assert (
            ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task.id).ok
            is True
        )

        lease = WorkerLease(
            tenant_id=tenant_id,
            task_id=task.id,
            holder_identity="metrics-no-mutate-worker",
            status=WorkerLeaseState.ACTIVE.value,
            heartbeat_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        setup_session.add(lease)
        task.metadata_json["worker_lease_id"] = str(lease.id)
        setup_session.commit()
        task_id = task.id
        lease_id = lease.id
    finally:
        setup_session.close()

    snapshot_session = session_factory()
    try:
        before_task = snapshot_session.get(ExecutionTask, task_id)
        before_lease = snapshot_session.get(WorkerLease, lease_id)
        assert before_task is not None
        assert before_lease is not None

        snapshot = _collect_snapshot(snapshot_session)
        assert snapshot.active_leases >= 1

        snapshot_session.expire_all()
        after_task = snapshot_session.get(ExecutionTask, task_id)
        after_lease = snapshot_session.get(WorkerLease, lease_id)
        assert after_task is not None
        assert after_lease is not None

        assert after_task.status == ExecutionTaskState.CLAIMED.value
        assert after_task.retry_count == 0
        assert after_lease.status == WorkerLeaseState.ACTIVE.value
    finally:
        snapshot_session.close()


def test_dead_lettered_task_is_not_reprocessed_by_claim_path(pg_engine, queue_adapter, redis_client) -> None:
    tenant_id = str(uuid.uuid4())
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    setup_session = session_factory()
    try:
        setup_session.add(
            Tenant(
                id=uuid.UUID(tenant_id),
                name="Dead Letter Claim Isolation Tenant",
                slug=f"dead-letter-claim-{tenant_id[:8]}",
                plan="free",
            )
        )
        mission = Mission(tenant_id=tenant_id, objective="dead-letter no reprocess", status="running")
        setup_session.add(mission)
        setup_session.flush()

        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="dead-letter terminal task",
            description="must not be claimed after dead-letter transition",
            status=ExecutionTaskState.DEAD_LETTERED.value,
            metadata_json={},
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        setup_session.add(task)
        setup_session.commit()
        task_id = task.id
    finally:
        setup_session.close()

    assert queue_adapter.claim_task(tenant_id=tenant_id, worker_id="worker-no-reprocess") is None
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:pending") == 0
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0

    verify_session = session_factory()
    try:
        leases = verify_session.scalars(
            select(WorkerLease).where(WorkerLease.tenant_id == tenant_id, WorkerLease.task_id == task_id)
        ).all()
        task = verify_session.get(ExecutionTask, task_id)
        assert task is not None
        assert task.status == ExecutionTaskState.DEAD_LETTERED.value
        assert leases == []
    finally:
        verify_session.close()
