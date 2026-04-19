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


def test_rg_mixed_tenant_concurrent_completion_cleanup_remains_isolated(
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
        task_a_id = task_a.id
        task_b_id = task_b.id
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_a))
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_b))
        result_a = ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_a, task_id=task_a_id)
        result_b = ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_b, task_id=task_b_id)
        assert result_a.ok is True
        assert result_b.ok is True
        setup_session.commit()
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    claimed: dict[str, tuple[str, str]] = {}

    def claim_and_complete(tenant_id: str, worker_name: str) -> None:
        session = session_factory()
        try:
            runtime = WorkerRuntimeService(session, queue_adapter)
            barrier.wait(timeout=5.0)
            task = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_name)
            assert task is not None
            lease_id = str(task.metadata_json["worker_lease_id"])
            claimed[tenant_id] = (str(task.id), lease_id)
            runtime.start_execution(
                tenant_id=tenant_id,
                lease_id=uuid.UUID(lease_id),
                worker_id=worker_name,
            )
            runtime.complete(
                tenant_id=tenant_id,
                lease_id=uuid.UUID(lease_id),
                worker_id=worker_name,
            )
            session.flush()
        finally:
            session.close()

    thread_a = threading.Thread(target=claim_and_complete, args=(tenant_a, "worker-rg-tenant-a-complete"), daemon=True)
    thread_b = threading.Thread(target=claim_and_complete, args=(tenant_b, "worker-rg-tenant-b-complete"), daemon=True)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=5.0)
    thread_b.join(timeout=5.0)
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    assert claimed[tenant_a][0] == str(task_a_id)
    assert claimed[tenant_b][0] == str(task_b_id)

    assert redis_client.llen(f"ajenda:queue:{tenant_a}:processing") == 0
    assert redis_client.llen(f"ajenda:queue:{tenant_b}:processing") == 0
    assert redis_client.get(f"ajenda:queue:{tenant_a}:lease:{task_a_id}") is None
    assert redis_client.get(f"ajenda:queue:{tenant_b}:lease:{task_b_id}") is None

    verify_session = session_factory()
    try:
        verified_task_a = verify_session.get(ExecutionTask, task_a_id)
        verified_task_b = verify_session.get(ExecutionTask, task_b_id)
        assert verified_task_a is not None
        assert verified_task_b is not None
        assert verified_task_a.tenant_id == tenant_a
        assert verified_task_b.tenant_id == tenant_b
        assert verified_task_a.status == ExecutionTaskState.COMPLETED.value
        assert verified_task_b.status == ExecutionTaskState.COMPLETED.value

        leases_a = verify_session.scalars(
            select(WorkerLease).where(
                WorkerLease.tenant_id == tenant_a,
                WorkerLease.task_id == task_a_id,
            )
        ).all()
        leases_b = verify_session.scalars(
            select(WorkerLease).where(
                WorkerLease.tenant_id == tenant_b,
                WorkerLease.task_id == task_b_id,
            )
        ).all()
        assert len(leases_a) == 1
        assert len(leases_b) == 1
        assert leases_a[0].status == WorkerLeaseState.RELEASED.value
        assert leases_b[0].status == WorkerLeaseState.RELEASED.value
        assert verified_task_a.metadata_json["worker_lease_id"] == str(leases_a[0].id)
        assert verified_task_b.metadata_json["worker_lease_id"] == str(leases_b[0].id)
    finally:
        verify_session.close()
