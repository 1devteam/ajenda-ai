from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
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


def _create_running_task(*, session_factory, queue_adapter, worker_id: str, metadata_json: dict[str, Any]):
    tenant_id = str(uuid.uuid4())
    setup_session = session_factory()
    try:
        tenant = Tenant(
            id=uuid.UUID(tenant_id),
            name="Dispatcher Failure Tenant",
            slug=f"dispatcher-failure-{tenant_id[:8]}",
            plan="free",
        )
        setup_session.add(tenant)
        mission = Mission(tenant_id=tenant_id, objective="Dispatcher failure mission", status="running")
        setup_session.add(mission)
        setup_session.flush()

        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="Dispatcher failure task",
            description="Task proves dispatcher failure state",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json=metadata_json,
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        setup_session.add(task)
        setup_session.flush()
        task_id = task.id

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
        return tenant_id, task_id, lease_id
    finally:
        setup_session.close()


def _lineage_count(*, session, tenant_id: str, task_id: uuid.UUID, lease_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(LineageRecord)
            .where(
                LineageRecord.tenant_id == tenant_id,
                LineageRecord.task_id == task_id,
                LineageRecord.worker_lease_id == lease_id,
                LineageRecord.relationship_type == "task_output",
            )
        )
        or 0
    )


def _assert_failed_without_output(
    *,
    session_factory,
    redis_client,
    tenant_id: str,
    task_id: uuid.UUID,
    lease_id: uuid.UUID,
) -> None:
    verify_session = session_factory()
    try:
        final_task = verify_session.get(ExecutionTask, task_id)
        final_lease = verify_session.get(WorkerLease, lease_id)

        assert final_task is not None
        assert final_task.status == ExecutionTaskState.FAILED.value
        assert final_lease is not None
        assert final_lease.status == WorkerLeaseState.RELEASED.value
        assert (
            _lineage_count(
                session=verify_session,
                tenant_id=tenant_id,
                task_id=task_id,
                lease_id=lease_id,
            )
            == 0
        )
        assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
        assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None
    finally:
        verify_session.close()


def test_dispatcher_invalid_task_type_marks_running_task_failed_without_output(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    worker_id = "worker-invalid-task-type"
    session_factory = _session_factory(pg_engine)
    tenant_id, task_id, lease_id = _create_running_task(
        session_factory=session_factory,
        queue_adapter=queue_adapter,
        worker_id=worker_id,
        metadata_json={"task_type": 123},
    )

    dispatcher = TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    )
    dispatcher.execute(task_id=task_id, lease_id=lease_id)

    _assert_failed_without_output(
        session_factory=session_factory,
        redis_client=redis_client,
        tenant_id=tenant_id,
        task_id=task_id,
        lease_id=lease_id,
    )


def test_dispatcher_invalid_handler_output_marks_running_task_failed_without_output(
    pg_engine,
    queue_adapter,
    redis_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_id = "worker-invalid-handler-output"
    session_factory = _session_factory(pg_engine)
    tenant_id, task_id, lease_id = _create_running_task(
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

    _assert_failed_without_output(
        session_factory=session_factory,
        redis_client=redis_client,
        tenant_id=tenant_id,
        task_id=task_id,
        lease_id=lease_id,
    )


def test_dispatcher_handler_exception_marks_running_task_failed_without_output(
    pg_engine,
    queue_adapter,
    redis_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_id = "worker-handler-exception"
    session_factory = _session_factory(pg_engine)
    tenant_id, task_id, lease_id = _create_running_task(
        session_factory=session_factory,
        queue_adapter=queue_adapter,
        worker_id=worker_id,
        metadata_json={"task_type": "raises_exception"},
    )

    def raising_handler(task: ExecutionTask, context: TaskHandlerContext) -> dict[str, Any]:
        raise RuntimeError("handler exploded during execution")

    monkeypatch.setattr(
        task_dispatcher,
        "_HANDLER_REGISTRY",
        {"raises_exception": cast(TaskHandler, raising_handler)},
    )
    monkeypatch.setattr(task_dispatcher, "_OUTPUT_REASON_BY_TASK_TYPE", {})

    dispatcher = TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    )
    dispatcher.execute(task_id=task_id, lease_id=lease_id)

    _assert_failed_without_output(
        session_factory=session_factory,
        redis_client=redis_client,
        tenant_id=tenant_id,
        task_id=task_id,
        lease_id=lease_id,
    )
