from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import Principal, PrincipalType
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.worker_runtime_service import WorkerRuntimeService

pytestmark = pytest.mark.integration


def _build_mission_app(
    *,
    tenant_id: uuid.UUID,
    session,
    queue_adapter,
) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="integration-mission-bridge-user",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
        )
        return await call_next(request)

    app.include_router(mission_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db():
        return session

    def _override_queue():
        return queue_adapter

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
    return app


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


def test_runtime_queue_admission_route_admits_current_materialized_tasks_real(
    pg_session,
    queue_adapter,
) -> None:
    tenant = Tenant(
        id=uuid.uuid4(),
        name="mission bridge proof",
        slug=f"mission-bridge-proof-{uuid.uuid4().hex[:8]}",
        plan="free",
    )
    pg_session.add(tenant)
    mission = Mission(
        tenant_id=str(tenant.id),
        objective="prove canonical mission bridge queue admission",
        status="running",
        metadata_json={},
    )
    pg_session.add(mission)
    pg_session.flush()

    materialized_tasks = []
    for index in range(2):
        task = ExecutionTask(
            tenant_id=str(tenant.id),
            mission_id=mission.id,
            title=f"bridge materialized task {index}",
            description="Real mission bridge runtime task",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={
                "task_type": "echo",
                "input": {"message": f"bridge-{index}"},
            },
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        pg_session.add(task)
        materialized_tasks.append(task)

    pg_session.flush()
    materialized_task_ids = [str(task.id) for task in materialized_tasks]
    mission.metadata_json = {
        "runtime_task_materialization": {
            "schema_version": 1,
            "mission_id": str(mission.id),
            "tenant_id": str(tenant.id),
            "materialization_status": "materialized",
            "created_execution_task_ids": materialized_task_ids,
            "materialized_execution_task_ids": materialized_task_ids,
            "runtime_authority": {
                "creates_execution_tasks": True,
                "enqueues_work": False,
                "dispatches_workers": False,
            },
        }
    }
    pg_session.commit()

    app = _build_mission_app(tenant_id=tenant.id, session=pg_session, queue_adapter=queue_adapter)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(f"/v1/missions/{mission.id}/runtime-queue-admission")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["admission_status"] == "admitted"
    assert set(body["admitted_task_ids"]) == set(materialized_task_ids)
    assert set(body["queued_task_ids"]) == set(materialized_task_ids)
    assert body["blocked_task_ids"] == []
    assert body["blockers"] == []

    pg_session.expire_all()
    persisted_mission = pg_session.get(Mission, mission.id)
    assert persisted_mission is not None
    persisted_admission = persisted_mission.metadata_json["runtime_queue_admission"]
    assert persisted_admission["admission_status"] == "admitted"
    assert set(persisted_admission["materialized_execution_task_ids"]) == set(materialized_task_ids)
    assert set(persisted_admission["admitted_execution_task_ids"]) == set(materialized_task_ids)
    assert persisted_admission["runtime_authority"] == {
        "creates_execution_tasks": False,
        "enqueues_work": True,
        "dispatches_workers": False,
        "executes_adapters": False,
        "calls_task_dispatcher": False,
        "calls_coordinator": True,
    }

    for task_id in materialized_task_ids:
        queued_task = pg_session.get(ExecutionTask, uuid.UUID(task_id))
        assert queued_task is not None
        assert queued_task.status == ExecutionTaskState.QUEUED.value

    claimed_ids = set()
    for index in range(2):
        claimed = queue_adapter.claim_task(tenant_id=str(tenant.id), worker_id=f"bridge-proof-worker-{index}")
        assert claimed is not None
        claimed_ids.add(str(claimed.task_id))
        assert claimed.tenant_id == str(tenant.id)
        assert claimed.mission_id == mission.id

    assert claimed_ids == set(materialized_task_ids)
