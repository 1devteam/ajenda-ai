from __future__ import annotations

import threading
import uuid

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


def test_rg_concurrent_claim_race_leaves_no_duplicate_processing_residue(
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
            else:
                results[worker_name] = None
        finally:
            session.close()

    thread_a = threading.Thread(target=claim, args=("worker-rg-residue-a",), daemon=True)
    thread_b = threading.Thread(target=claim, args=("worker-rg-residue-b",), daemon=True)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=5.0)
    thread_b.join(timeout=5.0)
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    success_ids = [value for value in results.values() if value is not None]
    assert success_ids == [str(task_id)]
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 1
    lease_key = redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}")
    assert lease_key is not None

    verify_session = session_factory()
    try:
        verified_task = verify_session.get(ExecutionTask, task_id)
        assert verified_task is not None
        assert verified_task.status == ExecutionTaskState.CLAIMED.value
        leases = verify_session.scalars(
            select(WorkerLease).where(
                WorkerLease.tenant_id == tenant_id,
                WorkerLease.task_id == task_id,
            )
        ).all()
        assert len(leases) == 1
        assert leases[0].status == WorkerLeaseState.CLAIMED.value
        assert verified_task.metadata_json["worker_lease_id"] == str(leases[0].id)
    finally:
        verify_session.close()


def test_rg_concurrent_claim_winner_completes_with_clean_terminal_cleanup(
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
            else:
                results[worker_name] = None
        finally:
            session.close()

    thread_a = threading.Thread(target=claim, args=("worker-rg-complete-a",), daemon=True)
    thread_b = threading.Thread(target=claim, args=("worker-rg-complete-b",), daemon=True)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=5.0)
    thread_b.join(timeout=5.0)
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    winners = [worker_name for worker_name, task_value in results.items() if task_value == str(task_id)]
    assert len(winners) == 1
    winning_worker = winners[0]

    completion_session = session_factory()
    try:
        task_row = completion_session.get(ExecutionTask, task_id)
        assert task_row is not None
        lease_id = uuid.UUID(str(task_row.metadata_json["worker_lease_id"]))
        runtime = WorkerRuntimeService(completion_session, queue_adapter)
        started = runtime.start_execution(
            tenant_id=tenant_id,
            lease_id=lease_id,
            worker_id=winning_worker,
        )
        assert started.status == ExecutionTaskState.RUNNING.value
        completed = runtime.complete(
            tenant_id=tenant_id,
            lease_id=lease_id,
            worker_id=winning_worker,
        )
        completion_session.flush()
        assert completed.status == ExecutionTaskState.COMPLETED.value
    finally:
        completion_session.close()

    assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
    assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None

    verify_session = session_factory()
    try:
        verified_task = verify_session.get(ExecutionTask, task_id)
        assert verified_task is not None
        assert verified_task.status == ExecutionTaskState.COMPLETED.value
        leases = verify_session.scalars(
            select(WorkerLease).where(
                WorkerLease.tenant_id == tenant_id,
                WorkerLease.task_id == task_id,
            )
        ).all()
        assert len(leases) == 1
        assert leases[0].status == WorkerLeaseState.RELEASED.value
    finally:
        verify_session.close()
