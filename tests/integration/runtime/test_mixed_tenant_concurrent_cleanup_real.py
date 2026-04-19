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


def _claim_concurrently(session_factory, queue_adapter, tenant_ids: tuple[str, str]) -> dict[str, str | None]:
    barrier = threading.Barrier(2)
    results: dict[str, str | None] = {}

    def claim(tenant_id: str, worker_name: str) -> None:
        session = session_factory()
        try:
            runtime = WorkerRuntimeService(session, queue_adapter)
            barrier.wait(timeout=5.0)
            claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_name)
            if claimed is not None:
                session.flush()
                results[tenant_id] = str(claimed.id)
                session.commit()
            else:
                results[tenant_id] = None
        finally:
            session.close()

    thread_a = threading.Thread(target=claim, args=(tenant_ids[0], "worker-rg-mixed-a"), daemon=True)
    thread_b = threading.Thread(target=claim, args=(tenant_ids[1], "worker-rg-mixed-b"), daemon=True)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=5.0)
    thread_b.join(timeout=5.0)
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()
    return results


def test_rg_mixed_tenant_post_race_completion_cleanup_stays_isolated(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    setup_session = session_factory()
    try:
        _create_tenant(setup_session, tenant_a)
        _create_tenant(setup_session, tenant_b)
        task_a = _create_task(setup_session, tenant_a)
        task_b = _create_task(setup_session, tenant_b)
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_a))
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_b))
        assert ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_a, task_id=task_a.id).ok is True
        assert ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_b, task_id=task_b.id).ok is True
        setup_session.commit()
    finally:
        setup_session.close()

    results = _claim_concurrently(session_factory, queue_adapter, (tenant_a, tenant_b))
    assert results[tenant_a] == str(task_a.id)
    assert results[tenant_b] == str(task_b.id)

    completion_session = session_factory()
    try:
        runtime = WorkerRuntimeService(completion_session, queue_adapter)
        task_row_a = completion_session.get(ExecutionTask, task_a.id)
        task_row_b = completion_session.get(ExecutionTask, task_b.id)
        assert task_row_a is not None
        assert task_row_b is not None
        lease_a = uuid.UUID(str(task_row_a.metadata_json["worker_lease_id"]))
        lease_b = uuid.UUID(str(task_row_b.metadata_json["worker_lease_id"]))

        runtime.start_execution(tenant_id=tenant_a, lease_id=lease_a, worker_id="worker-rg-mixed-a")
        runtime.complete(tenant_id=tenant_a, lease_id=lease_a, worker_id="worker-rg-mixed-a")
        runtime.start_execution(tenant_id=tenant_b, lease_id=lease_b, worker_id="worker-rg-mixed-b")
        runtime.complete(tenant_id=tenant_b, lease_id=lease_b, worker_id="worker-rg-mixed-b")
        completion_session.flush()
    finally:
        completion_session.close()

    assert redis_client.llen(f"ajenda:queue:{tenant_a}:processing") == 0
    assert redis_client.llen(f"ajenda:queue:{tenant_b}:processing") == 0
    assert redis_client.get(f"ajenda:queue:{tenant_a}:lease:{task_a.id}") is None
    assert redis_client.get(f"ajenda:queue:{tenant_b}:lease:{task_b.id}") is None

    verify_session = session_factory()
    try:
        verified_a = verify_session.get(ExecutionTask, task_a.id)
        verified_b = verify_session.get(ExecutionTask, task_b.id)
        assert verified_a is not None and verified_a.status == ExecutionTaskState.COMPLETED.value
        assert verified_b is not None and verified_b.status == ExecutionTaskState.COMPLETED.value
        leases_a = verify_session.scalars(select(WorkerLease).where(WorkerLease.tenant_id == tenant_a, WorkerLease.task_id == task_a.id)).all()
        leases_b = verify_session.scalars(select(WorkerLease).where(WorkerLease.tenant_id == tenant_b, WorkerLease.task_id == task_b.id)).all()
        assert len(leases_a) == 1 and leases_a[0].status == WorkerLeaseState.RELEASED.value
        assert len(leases_b) == 1 and leases_b[0].status == WorkerLeaseState.RELEASED.value
    finally:
        verify_session.close()


def test_rg_mixed_tenant_post_race_recovery_cleanup_stays_isolated(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    setup_session = session_factory()
    try:
        _create_tenant(setup_session, tenant_a)
        _create_tenant(setup_session, tenant_b)
        task_a = _create_task(setup_session, tenant_a)
        task_b = _create_task(setup_session, tenant_b)
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_a))
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_b))
        assert ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_a, task_id=task_a.id).ok is True
        assert ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_b, task_id=task_b.id).ok is True
        setup_session.commit()
    finally:
        setup_session.close()

    results = _claim_concurrently(session_factory, queue_adapter, (tenant_a, tenant_b))
    assert results[tenant_a] == str(task_a.id)
    assert results[tenant_b] == str(task_b.id)

    recovery_session = session_factory()
    try:
        task_row_a = recovery_session.get(ExecutionTask, task_a.id)
        task_row_b = recovery_session.get(ExecutionTask, task_b.id)
        assert task_row_a is not None
        assert task_row_b is not None
        lease_a = recovery_session.get(WorkerLease, uuid.UUID(str(task_row_a.metadata_json["worker_lease_id"])))
        lease_b = recovery_session.get(WorkerLease, uuid.UUID(str(task_row_b.metadata_json["worker_lease_id"])))
        assert lease_a is not None
        assert lease_b is not None
        lease_a.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        lease_b.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        recovery_session.flush()

        summary = RuntimeMaintainer(recovery_session, queue_adapter, expiry_seconds=30, max_retries=3).recover_expired_leases()
        recovery_session.flush()
        assert summary.expired_lease_count == 2
        assert summary.requeued_task_count == 2
        assert summary.dead_lettered_count == 0
    finally:
        recovery_session.close()

    assert redis_client.llen(f"ajenda:queue:{tenant_a}:processing") == 0
    assert redis_client.llen(f"ajenda:queue:{tenant_b}:processing") == 0
    assert redis_client.get(f"ajenda:queue:{tenant_a}:lease:{task_a.id}") is None
    assert redis_client.get(f"ajenda:queue:{tenant_b}:lease:{task_b.id}") is None
    assert redis_client.llen(f"ajenda:queue:{tenant_a}:pending") >= 1
    assert redis_client.llen(f"ajenda:queue:{tenant_b}:pending") >= 1

    verify_session = session_factory()
    try:
        verified_a = verify_session.get(ExecutionTask, task_a.id)
        verified_b = verify_session.get(ExecutionTask, task_b.id)
        assert verified_a is not None and verified_a.status == ExecutionTaskState.QUEUED.value and verified_a.retry_count == 1
        assert verified_b is not None and verified_b.status == ExecutionTaskState.QUEUED.value and verified_b.retry_count == 1
        leases_a = verify_session.scalars(select(WorkerLease).where(WorkerLease.tenant_id == tenant_a, WorkerLease.task_id == task_a.id)).all()
        leases_b = verify_session.scalars(select(WorkerLease).where(WorkerLease.tenant_id == tenant_b, WorkerLease.task_id == task_b.id)).all()
        assert len(leases_a) == 1 and leases_a[0].status == WorkerLeaseState.EXPIRED.value
        assert len(leases_b) == 1 and leases_b[0].status == WorkerLeaseState.EXPIRED.value
    finally:
        verify_session.close()


def test_rg_mixed_tenant_post_race_dead_letter_cleanup_stays_isolated(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    setup_session = session_factory()
    try:
        _create_tenant(setup_session, tenant_a)
        _create_tenant(setup_session, tenant_b)
        task_a = _create_task(setup_session, tenant_a)
        task_b = _create_task(setup_session, tenant_b)
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_a))
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_b))
        assert ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_a, task_id=task_a.id).ok is True
        assert ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_b, task_id=task_b.id).ok is True
        setup_session.commit()
    finally:
        setup_session.close()

    results = _claim_concurrently(session_factory, queue_adapter, (tenant_a, tenant_b))
    assert results[tenant_a] == str(task_a.id)
    assert results[tenant_b] == str(task_b.id)

    recovery_session = session_factory()
    try:
        task_row_a = recovery_session.get(ExecutionTask, task_a.id)
        task_row_b = recovery_session.get(ExecutionTask, task_b.id)
        assert task_row_a is not None
        assert task_row_b is not None
        task_row_a.retry_count = 3
        task_row_b.retry_count = 3
        lease_a = recovery_session.get(WorkerLease, uuid.UUID(str(task_row_a.metadata_json["worker_lease_id"])))
        lease_b = recovery_session.get(WorkerLease, uuid.UUID(str(task_row_b.metadata_json["worker_lease_id"])))
        assert lease_a is not None
        assert lease_b is not None
        lease_a.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        lease_b.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        recovery_session.flush()

        summary = RuntimeMaintainer(recovery_session, queue_adapter, expiry_seconds=30, max_retries=3).recover_expired_leases()
        recovery_session.flush()
        assert summary.expired_lease_count == 2
        assert summary.requeued_task_count == 0
        assert summary.dead_lettered_count == 2
    finally:
        recovery_session.close()

    assert redis_client.llen(f"ajenda:queue:{tenant_a}:processing") == 0
    assert redis_client.llen(f"ajenda:queue:{tenant_b}:processing") == 0
    assert redis_client.get(f"ajenda:queue:{tenant_a}:lease:{task_a.id}") is None
    assert redis_client.get(f"ajenda:queue:{tenant_b}:lease:{task_b.id}") is None
    assert redis_client.llen(f"ajenda:queue:{tenant_a}:pending") == 0
    assert redis_client.llen(f"ajenda:queue:{tenant_b}:pending") == 0

    verify_session = session_factory()
    try:
        verified_a = verify_session.get(ExecutionTask, task_a.id)
        verified_b = verify_session.get(ExecutionTask, task_b.id)
        assert verified_a is not None and verified_a.status == ExecutionTaskState.DEAD_LETTERED.value
        assert verified_b is not None and verified_b.status == ExecutionTaskState.DEAD_LETTERED.value
        leases_a = verify_session.scalars(select(WorkerLease).where(WorkerLease.tenant_id == tenant_a, WorkerLease.task_id == task_a.id)).all()
        leases_b = verify_session.scalars(select(WorkerLease).where(WorkerLease.tenant_id == tenant_b, WorkerLease.task_id == task_b.id)).all()
        assert len(leases_a) == 1 and leases_a[0].status == WorkerLeaseState.EXPIRED.value
        assert len(leases_b) == 1 and leases_b[0].status == WorkerLeaseState.EXPIRED.value
    finally:
        verify_session.close()


def test_rg_mixed_tenant_asymmetric_post_race_cleanup_stays_isolated(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    setup_session = session_factory()
    try:
        _create_tenant(setup_session, tenant_a)
        _create_tenant(setup_session, tenant_b)
        task_a = _create_task(setup_session, tenant_a)
        task_b = _create_task(setup_session, tenant_b)
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_a))
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_b))
        assert ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_a, task_id=task_a.id).ok is True
        assert ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_b, task_id=task_b.id).ok is True
        setup_session.commit()
    finally:
        setup_session.close()

    results = _claim_concurrently(session_factory, queue_adapter, (tenant_a, tenant_b))
    assert results[tenant_a] == str(task_a.id)
    assert results[tenant_b] == str(task_b.id)

    mutation_session = session_factory()
    try:
        runtime = WorkerRuntimeService(mutation_session, queue_adapter)
        task_row_a = mutation_session.get(ExecutionTask, task_a.id)
        task_row_b = mutation_session.get(ExecutionTask, task_b.id)
        assert task_row_a is not None
        assert task_row_b is not None
        lease_a = mutation_session.get(WorkerLease, uuid.UUID(str(task_row_a.metadata_json["worker_lease_id"])))
        lease_b = mutation_session.get(WorkerLease, uuid.UUID(str(task_row_b.metadata_json["worker_lease_id"])))
        assert lease_a is not None
        assert lease_b is not None

        runtime.start_execution(tenant_id=tenant_a, lease_id=lease_a.id, worker_id="worker-rg-mixed-a")
        runtime.complete(tenant_id=tenant_a, lease_id=lease_a.id, worker_id="worker-rg-mixed-a")

        task_row_b.retry_count = 3
        lease_b.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        mutation_session.flush()

        summary = RuntimeMaintainer(mutation_session, queue_adapter, expiry_seconds=30, max_retries=3).recover_expired_leases()
        mutation_session.flush()
        assert summary.expired_lease_count == 1
        assert summary.requeued_task_count == 0
        assert summary.dead_lettered_count == 1
    finally:
        mutation_session.close()

    assert redis_client.llen(f"ajenda:queue:{tenant_a}:processing") == 0
    assert redis_client.llen(f"ajenda:queue:{tenant_b}:processing") == 0
    assert redis_client.get(f"ajenda:queue:{tenant_a}:lease:{task_a.id}") is None
    assert redis_client.get(f"ajenda:queue:{tenant_b}:lease:{task_b.id}") is None
    assert redis_client.llen(f"ajenda:queue:{tenant_a}:pending") == 0
    assert redis_client.llen(f"ajenda:queue:{tenant_b}:pending") == 0

    verify_session = session_factory()
    try:
        verified_a = verify_session.get(ExecutionTask, task_a.id)
        verified_b = verify_session.get(ExecutionTask, task_b.id)
        assert verified_a is not None and verified_a.status == ExecutionTaskState.COMPLETED.value
        assert verified_b is not None and verified_b.status == ExecutionTaskState.DEAD_LETTERED.value
        leases_a = verify_session.scalars(select(WorkerLease).where(WorkerLease.tenant_id == tenant_a, WorkerLease.task_id == task_a.id)).all()
        leases_b = verify_session.scalars(select(WorkerLease).where(WorkerLease.tenant_id == tenant_b, WorkerLease.task_id == task_b.id)).all()
        assert len(leases_a) == 1 and leases_a[0].status == WorkerLeaseState.RELEASED.value
        assert len(leases_b) == 1 and leases_b[0].status == WorkerLeaseState.EXPIRED.value
    finally:
        verify_session.close()
