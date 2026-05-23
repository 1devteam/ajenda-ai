from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.worker_runtime_service import WorkerRuntimeService

pytestmark = pytest.mark.integration


def test_materialized_tasks_require_post_commit_queue_admission_and_execute_once(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    tenant_id = str(uuid.uuid4())
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    pending_key = f"ajenda:queue:{tenant_id}:pending"
    processing_key = f"ajenda:queue:{tenant_id}:processing"
    dead_letter_key = f"ajenda:queue:{tenant_id}:dead_letter"
    pending_baseline = redis_client.llen(pending_key)
    processing_baseline = redis_client.llen(processing_key)
    dead_letter_baseline = redis_client.hlen(dead_letter_key)

    seed = session_factory()
    try:
        seed.add(Tenant(id=uuid.UUID(tenant_id), name="proof", slug=f"proof-{tenant_id[:8]}", plan="free"))
        mission = Mission(tenant_id=tenant_id, objective="prove boundary", status="running")
        seed.add(mission)
        seed.flush()

        tasks = []
        for index in range(2):
            task = ExecutionTask(
                tenant_id=tenant_id,
                mission_id=mission.id,
                title=f"materialized task {index}",
                description="materialized runtime task",
                status=ExecutionTaskState.PLANNED.value,
                metadata_json={"task_type": "echo", "input": {"message": f"hello-{index}"}},
                compliance_category="operational",
                jurisdiction="US-ALL",
                requires_human_review=False,
            )
            seed.add(task)
            tasks.append(task)

        seed.flush()
        task_ids = [task.id for task in tasks]
        seed.commit()

        coordinator = ExecutionCoordinator(seed, queue_adapter)
        for task_id in task_ids:
            result = coordinator.queue_task(tenant_id=tenant_id, task_id=task_id)
            assert result.ok is True

        seed.commit()
    finally:
        seed.close()

    runtime_a = session_factory()
    runtime_b = session_factory()
    try:
        service_a = WorkerRuntimeService(runtime_a, queue_adapter)
        service_b = WorkerRuntimeService(runtime_b, queue_adapter)

        claimed_a = service_a.claim_next_task(tenant_id=tenant_id, worker_id="worker-a")
        claimed_b = service_b.claim_next_task(tenant_id=tenant_id, worker_id="worker-b")
        assert claimed_a is not None
        assert claimed_b is not None
        assert claimed_a.id != claimed_b.id

        for service, claimed, worker_id in (
            (service_a, claimed_a, "worker-a"),
            (service_b, claimed_b, "worker-b"),
        ):
            lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
            service.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
            service.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
            service.complete(
                tenant_id=tenant_id,
                lease_id=lease_id,
                worker_id=worker_id,
                task_output={"worker": worker_id},
                output_reason="runtime admission proof",
            )
    finally:
        runtime_a.close()
        runtime_b.close()

    verify = session_factory()
    try:
        rows = verify.scalars(select(ExecutionTask).where(ExecutionTask.tenant_id == tenant_id)).all()
        assert len(rows) == 2
        assert all(row.status == ExecutionTaskState.COMPLETED.value for row in rows)

        lease_ids = [row.metadata_json.get("worker_lease_id") for row in rows]
        assert None not in lease_ids
        assert len(set(lease_ids)) == len(lease_ids)

        lease_rows = verify.scalars(select(WorkerLease).where(WorkerLease.tenant_id == tenant_id)).all()
        assert len(lease_rows) == 2
    finally:
        verify.close()

    assert redis_client.llen(pending_key) == pending_baseline
    assert redis_client.llen(processing_key) == processing_baseline
    assert redis_client.hlen(dead_letter_key) == dead_letter_baseline
