from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.runtime_queue_dispatch import RuntimeQueueDispatch
from backend.domain.tenant import Tenant
from backend.domain.tenant_usage import TenantUsage
from backend.queue.base import QueueAdapter, QueueOperationResult
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.runtime_queue_dispatcher import RuntimeQueueDispatchService
from backend.services.worker_runtime_service import WorkerRuntimeService

pytestmark = pytest.mark.integration


def _sessions(pg_engine) -> sessionmaker:  # type: ignore[no-untyped-def, type-arg]
    return sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def _create_planned_task(session: Session, *, label: str) -> tuple[Tenant, ExecutionTask]:
    tenant_id = uuid.uuid4()
    tenant = Tenant(
        id=tenant_id,
        name=f"Dispatch {label}",
        slug=f"dispatch-{label}-{tenant_id.hex[:8]}",
        plan="free",
    )
    session.add(tenant)
    session.flush()
    mission = Mission(
        tenant_id=str(tenant_id),
        objective=f"Runtime queue dispatch {label}",
        status="running",
    )
    session.add(mission)
    session.flush()
    task = ExecutionTask(
        tenant_id=str(tenant_id),
        mission_id=mission.id,
        title=f"Dispatch {label}",
        description="Prove durable DB-to-queue publication",
        status=ExecutionTaskState.PLANNED.value,
        metadata_json={"task_type": "echo", "input": {"message": label}},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    session.add(task)
    session.flush()
    return tenant, task


def _tasks_created(session: Session, tenant_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(TenantUsage.tasks_created), 0)).where(TenantUsage.tenant_id == tenant_id)
        )
        or 0
    )


def test_rollback_discards_dispatch_intent_queue_message_and_quota(pg_engine, queue_adapter: QueueAdapter) -> None:
    sessions = _sessions(pg_engine)
    setup = sessions()
    tenant, task = _create_planned_task(setup, label="rollback")
    setup.commit()
    setup.close()

    admission = sessions()
    result = ExecutionCoordinator(admission, queue_adapter).queue_task(
        tenant_id=str(tenant.id),
        task_id=task.id,
    )
    assert result.ok is True
    admission.rollback()
    admission.close()

    assert queue_adapter.pending_depth(tenant_id=str(tenant.id)) == 0

    verify = sessions()
    persisted_task = verify.get(ExecutionTask, task.id)
    assert persisted_task is not None
    assert persisted_task.status == ExecutionTaskState.PLANNED.value
    assert verify.scalar(select(RuntimeQueueDispatch).where(RuntimeQueueDispatch.task_id == task.id)) is None
    assert _tasks_created(verify, tenant.id) == 0
    verify.close()


def test_lost_publish_ack_reconciles_without_duplicate_delivery(
    pg_engine,
    queue_adapter: QueueAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = _sessions(pg_engine)
    setup = sessions()
    tenant, task = _create_planned_task(setup, label="lost-ack")
    setup.commit()
    setup.close()

    real_enqueue = queue_adapter.enqueue_task_idempotent

    def _publish_then_lose_ack(message, *, idempotency_key):  # type: ignore[no-untyped-def]
        published = real_enqueue(message, idempotency_key=idempotency_key)
        assert published.ok is True
        return QueueOperationResult(ok=False, reason="simulated publisher crash before DB acknowledgement")

    monkeypatch.setattr(queue_adapter, "enqueue_task_idempotent", _publish_then_lose_ack)
    admission = sessions()
    assert (
        ExecutionCoordinator(admission, queue_adapter)
        .queue_task(
            tenant_id=str(tenant.id),
            task_id=task.id,
        )
        .ok
    )
    admission.commit()
    admission.close()

    assert queue_adapter.pending_depth(tenant_id=str(tenant.id)) == 1

    monkeypatch.setattr(queue_adapter, "enqueue_task_idempotent", real_enqueue)
    reconcile = sessions()
    dispatch = reconcile.scalar(select(RuntimeQueueDispatch).where(RuntimeQueueDispatch.task_id == task.id))
    assert dispatch is not None
    assert dispatch.status == "pending"
    assert dispatch.attempt_count == 1
    dispatch.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    reconcile.commit()

    summary = RuntimeQueueDispatchService(reconcile, queue_adapter).publish_due()
    assert summary.published_count == 1
    reconcile.close()

    assert queue_adapter.pending_depth(tenant_id=str(tenant.id)) == 1
    claimed = queue_adapter.claim_task(tenant_id=str(tenant.id), worker_id="lost-ack-worker")
    assert claimed is not None
    assert claimed.task_id == task.id
    assert queue_adapter.claim_task(tenant_id=str(tenant.id), worker_id="duplicate-worker") is None

    verify = sessions()
    persisted_dispatch = verify.scalar(select(RuntimeQueueDispatch).where(RuntimeQueueDispatch.task_id == task.id))
    assert persisted_dispatch is not None
    assert persisted_dispatch.status == "published"
    assert persisted_dispatch.attempt_count == 2
    verify.close()


def test_cancellation_removes_only_the_tenant_owned_pending_payload(
    pg_engine,
    queue_adapter: QueueAdapter,
) -> None:
    sessions = _sessions(pg_engine)
    setup = sessions()
    tenant_a, task_a = _create_planned_task(setup, label="cancel-a")
    tenant_b, task_b = _create_planned_task(setup, label="cancel-b")
    setup.commit()
    setup.close()

    admission = sessions()
    assert ExecutionCoordinator(admission, queue_adapter).queue_task(tenant_id=str(tenant_a.id), task_id=task_a.id).ok
    assert ExecutionCoordinator(admission, queue_adapter).queue_task(tenant_id=str(tenant_b.id), task_id=task_b.id).ok
    admission.commit()
    admission.close()

    assert queue_adapter.pending_depth(tenant_id=str(tenant_a.id)) == 1
    assert queue_adapter.pending_depth(tenant_id=str(tenant_b.id)) == 1

    cancellation = sessions()
    cancelled = WorkerRuntimeService(cancellation, queue_adapter).cancel_task(
        tenant_id=str(tenant_a.id),
        task_id=task_a.id,
        actor="integration-operator",
        reason="cancel before claim",
    )
    assert cancelled.status == ExecutionTaskState.CANCELLED.value
    cancellation.close()

    assert queue_adapter.pending_depth(tenant_id=str(tenant_a.id)) == 0
    assert queue_adapter.pending_depth(tenant_id=str(tenant_b.id)) == 1

    verify = sessions()
    dispatch_a = verify.scalar(select(RuntimeQueueDispatch).where(RuntimeQueueDispatch.task_id == task_a.id))
    dispatch_b = verify.scalar(select(RuntimeQueueDispatch).where(RuntimeQueueDispatch.task_id == task_b.id))
    assert dispatch_a is not None
    assert dispatch_a.status == "cancelled"
    assert dispatch_a.cancelled_at is not None
    assert dispatch_b is not None
    assert dispatch_b.status == "published"
    verify.close()
