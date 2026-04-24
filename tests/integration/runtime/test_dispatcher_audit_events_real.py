from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers import task_dispatcher
from backend.workers.task_dispatcher import TaskDispatcher, TaskHandler, TaskHandlerContext

pytestmark = pytest.mark.integration


def _session_factory(pg_engine):
    return sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def _create_running_task(
    *,
    session_factory,
    queue_adapter,
    worker_id: str,
    metadata_json: dict[str, Any],
):
    tenant_id = str(uuid.uuid4())
    setup_session = session_factory()
    try:
        tenant = Tenant(
            id=uuid.UUID(tenant_id),
            name="Dispatcher Audit Tenant",
            slug=f"dispatcher-audit-{tenant_id[:8]}",
            plan="free",
        )
        setup_session.add(tenant)
        mission = Mission(tenant_id=tenant_id, objective="Dispatcher audit mission", status="running")
        setup_session.add(mission)
        setup_session.flush()

        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="Dispatcher audit task",
            description="Task proves dispatcher audit event state",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json=metadata_json,
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        setup_session.add(task)
        setup_session.flush()
        task_id = task.id
        mission_id = mission.id

        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_id))
        queued = ExecutionCoordinator(setup_session, queue_adapter).queue_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )
        assert queued.ok is True

        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup_session.commit()
        return tenant_id, mission_id, task_id, lease_id
    finally:
        setup_session.close()


def _audit_events_for_task(*, session, tenant_id: str, task_id: uuid.UUID) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.payload_json["task_id"].astext == str(task_id),
            )
            .order_by(AuditEvent.created_at.asc())
        )
    )


def test_dispatcher_success_writes_completed_worker_audit_event(
    pg_engine,
    queue_adapter,
) -> None:
    worker_id = "worker-audit-complete"
    session_factory = _session_factory(pg_engine)
    tenant_id, mission_id, task_id, lease_id = _create_running_task(
        session_factory=session_factory,
        queue_adapter=queue_adapter,
        worker_id=worker_id,
        metadata_json={"task_type": "echo", "input": {"message": "audit"}},
    )

    dispatcher = TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    )
    dispatcher.execute(task_id=task_id, lease_id=lease_id)

    verify_session = session_factory()
    try:
        events = _audit_events_for_task(session=verify_session, tenant_id=tenant_id, task_id=task_id)
        completed_events = [event for event in events if event.action == "task_completed"]

        assert len(completed_events) == 1
        event = completed_events[0]
        assert event.tenant_id == tenant_id
        assert event.mission_id == mission_id
        assert event.category == "worker"
        assert event.actor == worker_id
        assert event.details == f"Completed task {task_id}"
        assert event.payload_json == {"task_id": str(task_id), "lease_id": str(lease_id)}
    finally:
        verify_session.close()


def test_dispatcher_failure_writes_failed_worker_audit_event(
    pg_engine,
    queue_adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_id = "worker-audit-failed"
    failure_reason = 'task handler result status must be "completed"'
    session_factory = _session_factory(pg_engine)
    tenant_id, mission_id, task_id, lease_id = _create_running_task(
        session_factory=session_factory,
        queue_adapter=queue_adapter,
        worker_id=worker_id,
        metadata_json={"task_type": "invalid_output"},
    )

    def invalid_output_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        return {"handler": "invalid_output", "status": "failed"}

    monkeypatch.setattr(
        task_dispatcher,
        "_HANDLER_REGISTRY",
        {"invalid_output": cast(TaskHandler, invalid_output_handler)},
    )
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", {})

    dispatcher = TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    )
    dispatcher.execute(task_id=task_id, lease_id=lease_id)

    verify_session = session_factory()
    try:
        events = _audit_events_for_task(session=verify_session, tenant_id=tenant_id, task_id=task_id)
        failed_events = [event for event in events if event.action == "task_failed"]

        assert len(failed_events) == 1
        event = failed_events[0]
        assert event.tenant_id == tenant_id
        assert event.mission_id == mission_id
        assert event.category == "worker"
        assert event.actor == worker_id
        assert event.details == failure_reason
        assert event.payload_json == {"task_id": str(task_id), "lease_id": str(lease_id)}
    finally:
        verify_session.close()
