from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.routes import task as task_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import Principal, PrincipalType
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.tenant_usage import TenantUsage
from backend.queue.base import QueueAdapter

pytestmark = pytest.mark.integration


def _build_app(
    *,
    tenant_id: uuid.UUID,
    session: Session,
    queue_adapter: QueueAdapter,
    roles: tuple[str, ...] | None = ("tenant_admin",),
) -> FastAPI:
    app = FastAPI()

    if roles is not None:

        @app.middleware("http")
        async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
            request.state.principal = Principal(
                subject_id="integration-task-queue-user",
                tenant_id=str(tenant_id),
                principal_type=PrincipalType.USER,
                roles=roles,
            )
            return await call_next(request)

    app.include_router(task_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> Session:
        return session

    def _override_queue() -> QueueAdapter:
        return queue_adapter

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
    return app


def _create_tenant(session: Session, *, name: str) -> Tenant:
    tenant_id = uuid.uuid4()
    tenant = Tenant(
        id=tenant_id,
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{tenant_id.hex[:8]}",
        plan="free",
    )
    session.add(tenant)
    session.flush()
    return tenant


def _create_planned_task(session: Session, *, tenant: Tenant) -> tuple[Mission, ExecutionTask]:
    mission = Mission(
        tenant_id=str(tenant.id),
        objective="Real API task queue proof mission",
        status="running",
    )
    session.add(mission)
    session.flush()

    task = ExecutionTask(
        tenant_id=str(tenant.id),
        mission_id=mission.id,
        title="Real API task queue proof task",
        description="Queued through FastAPI TestClient with real Postgres and Redis",
        status=ExecutionTaskState.PLANNED.value,
        metadata_json={"task_type": "echo", "input": {"message": "api-route-proof"}},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    session.add(task)
    session.flush()
    return mission, task


def _tasks_created(session: Session, tenant_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(TenantUsage.tasks_created), 0)).where(TenantUsage.tenant_id == tenant_id)
        )
        or 0
    )


def test_task_queue_route_queues_real_task_in_postgres_and_redis(
    pg_session: Session,
    queue_adapter: QueueAdapter,
) -> None:
    tenant = _create_tenant(pg_session, name="API Queue Tenant")
    _, task = _create_planned_task(pg_session, tenant=tenant)
    pg_session.commit()

    app = _build_app(tenant_id=tenant.id, session=pg_session, queue_adapter=queue_adapter)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(f"/v1/tasks/{task.id}/queue")

    assert response.status_code == 200
    assert response.json() == {"task_id": str(task.id), "state": ExecutionTaskState.QUEUED.value}
    assert _tasks_created(pg_session, tenant.id) == 0

    pg_session.expire_all()
    queued_task = pg_session.get(ExecutionTask, task.id)
    assert queued_task is not None
    assert queued_task.status == ExecutionTaskState.QUEUED.value

    claimed = queue_adapter.claim_task(tenant_id=str(tenant.id), worker_id="api-route-proof-worker")
    assert claimed is not None
    assert claimed.tenant_id == str(tenant.id)
    assert claimed.task_id == task.id
    assert claimed.mission_id == task.mission_id
    assert claimed.payload == task.metadata_json


def test_task_queue_route_blocks_foreign_tenant_without_queue_or_quota_usage(
    pg_session: Session,
    queue_adapter: QueueAdapter,
) -> None:
    owning_tenant = _create_tenant(pg_session, name="API Queue Owner")
    caller_tenant = _create_tenant(pg_session, name="API Queue Caller")
    _, task = _create_planned_task(pg_session, tenant=owning_tenant)
    pg_session.commit()

    app = _build_app(tenant_id=caller_tenant.id, session=pg_session, queue_adapter=queue_adapter)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(f"/v1/tasks/{task.id}/queue")

    assert response.status_code == 400
    assert response.json() == {"detail": "task not found for tenant"}
    assert _tasks_created(pg_session, caller_tenant.id) == 0

    claimed_for_owner = queue_adapter.claim_task(tenant_id=str(owning_tenant.id), worker_id="api-route-proof-worker")
    claimed_for_caller = queue_adapter.claim_task(tenant_id=str(caller_tenant.id), worker_id="api-route-proof-worker")
    assert claimed_for_owner is None
    assert claimed_for_caller is None

    pg_session.expire_all()
    unchanged_task = pg_session.get(ExecutionTask, task.id)
    assert unchanged_task is not None
    assert unchanged_task.status == ExecutionTaskState.PLANNED.value


def test_task_queue_route_blocks_missing_task_without_quota_usage(
    pg_session: Session,
    queue_adapter: QueueAdapter,
) -> None:
    tenant = _create_tenant(pg_session, name="API Queue Missing")
    missing_task_id = uuid.uuid4()
    pg_session.commit()

    app = _build_app(tenant_id=tenant.id, session=pg_session, queue_adapter=queue_adapter)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(f"/v1/tasks/{missing_task_id}/queue")

    assert response.status_code == 400
    assert response.json() == {"detail": "task not found for tenant"}
    assert _tasks_created(pg_session, tenant.id) == 0

    claimed = queue_adapter.claim_task(tenant_id=str(tenant.id), worker_id="api-route-proof-worker")
    assert claimed is None


def test_task_queue_route_rejects_missing_auth_before_queue_or_quota_usage(
    pg_session: Session,
    queue_adapter: QueueAdapter,
) -> None:
    tenant = _create_tenant(pg_session, name="API Queue Unauthenticated")
    _, task = _create_planned_task(pg_session, tenant=tenant)
    pg_session.commit()

    app = _build_app(tenant_id=tenant.id, session=pg_session, queue_adapter=queue_adapter, roles=None)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(f"/v1/tasks/{task.id}/queue")

    assert response.status_code == 401
    assert response.json() == {"detail": "missing authentication"}
    assert _tasks_created(pg_session, tenant.id) == 0

    claimed = queue_adapter.claim_task(tenant_id=str(tenant.id), worker_id="api-route-proof-worker")
    assert claimed is None

    pg_session.expire_all()
    unchanged_task = pg_session.get(ExecutionTask, task.id)
    assert unchanged_task is not None
    assert unchanged_task.status == ExecutionTaskState.PLANNED.value
