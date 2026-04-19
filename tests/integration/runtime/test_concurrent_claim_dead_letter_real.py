from __future__ import annotations

import threading
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
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.runtime_maintainer import RuntimeMaintainer
from backend.services.worker_runtime_service import WorkerRuntimeService

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


def _create_task(pg_session, tenant_id: str) -> ExecutionTask:
    mission = Mission(tenant_id=tenant_id, objective="RG mission", status="running")
    pg_session.add(mission)
    pg_session.flush()
    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=mission.id,
        title="RG task",
        description="RG task description",
        status=ExecutionTaskState.PLANNED.value,
        metadata_json={},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    pg_session.add(task)
    pg_session.flush()
    return task


def test_rg_previously_raced_work_dead_letters_once_at_recovery_exhaustion(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    tenant_id = str(uuid.uuid4())
    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    setup_session = session_factory()
    try:
        _create_tenant(setup_session, tenant_id)
        task = _create_task(setup_session, tenant_id)
        task_id = task.id
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_id))
        result = ExecutionCoordinator(setup_session, queue_adapter).queue_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )
        assert result.ok is True
        setup_session.commit()
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: dict[str, str | None] = {}

    def claim(worker_name: str) -> None:
        session = session_factory()
        try:
            runtime = WorkerRuntimeService(session, queue_adapter)
            barrier.wait(timeout=5.0)
            claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_name)
            if claimed is not None:
                session.flush()
                results[worker_name] = str(claimed.id)
                session.commit()
            else:
                results[worker_name] = None
        finally:
            session.close()

    thread_a = threading.Thread(target=claim, args=("worker-rg-dead-letter-a",), daemon=True)
    thread_b = threading.Thread(target=claim, args=("worker-rg-dead-letter-b",), daemon=True)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=5.0)
    thread_b.join(timeout=5.0)
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    winners = [worker_name for worker_name, task_value in results.items() if task_value == str(task_id)]
    assert len(winners) == 1

    exhaust_session = session_factory()
    try:
        task_row = exhaust_session.get(ExecutionTask, task_id)
        assert task_row is not None
        task_row.retry_count = 3
        lease_id = uuid.UUID(str(task_row.metadata_json["worker_lease_id"]))
        lease = exhaust_session.get(WorkerLease, lease_id)
        assert lease is not None
        lease.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        exhaust_session.flush()

        summary = RuntimeMaintainer(exhaust_session, queue_adapter, expiry_seconds=30, max_retries=3).recover_expired_leases()
        exhaust_session.flush()

        assert summary.expired_lease_count == 1
        assert summary.requeued_task_count == 0
        assert summary.dead_lettered_count == 1
    finally:
        exhaust_session.close()

    assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
    assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:pending") == 0
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:dead_letter") >= 1

    verify_session = session_factory()
    try:
        verified_task = verify_session.get(ExecutionTask, task_id)
        assert verified_task is not None
        assert verified_task.status == ExecutionTaskState.DEAD_LETTERED.value
        assert verified_task.retry_count == 3
        leases = verify_session.scalars(
            select(WorkerLease).where(
                WorkerLease.tenant_id == tenant_id,
                WorkerLease.task_id == task_id,
            )
        ).all()
        assert len(leases) == 1
        assert leases[0].status == WorkerLeaseState.EXPIRED.value
        assert verified_task.metadata_json["worker_lease_id"] == str(leases[0].id)
    finally:
        verify_session.close()
