from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.domain.enums import ExecutionTaskState, MissionState
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


def test_retry_publishes_only_after_queued_state_is_committed(
    pg_engine,
    queue_adapter: QueueAdapter,
) -> None:
    """A worker cannot consume a retry while the database still says terminal."""

    sessions = _sessions(pg_engine)
    setup = sessions()
    tenant, task = _create_planned_task(setup, label="retry-after-commit")
    setup.commit()
    setup.close()

    admission = sessions()
    assert ExecutionCoordinator(admission, queue_adapter).queue_task(tenant_id=str(tenant.id), task_id=task.id).ok
    admission.commit()
    admission.close()

    failure = sessions()
    runtime = WorkerRuntimeService(failure, queue_adapter)
    claimed = runtime.claim_next_task(tenant_id=str(tenant.id), worker_id="initial-worker")
    assert claimed is not None
    lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
    runtime.start_execution(tenant_id=str(tenant.id), lease_id=lease_id, worker_id="initial-worker")
    runtime.fail(
        tenant_id=str(tenant.id),
        lease_id=lease_id,
        worker_id="initial-worker",
        reason="synthetic terminal failure for retry proof",
    )
    failure.close()

    retry = sessions()
    result = ExecutionCoordinator(retry, queue_adapter).retry_task(tenant_id=str(tenant.id), task_id=task.id)
    assert result.ok is True
    # The queue is still empty before commit: publication is after-commit only.
    assert queue_adapter.pending_depth(tenant_id=str(tenant.id)) == 0
    retry.commit()
    retry.close()

    assert queue_adapter.pending_depth(tenant_id=str(tenant.id)) == 1
    verify = sessions()
    retried_task = verify.get(ExecutionTask, task.id)
    dispatch = verify.scalar(select(RuntimeQueueDispatch).where(RuntimeQueueDispatch.task_id == task.id))
    assert retried_task is not None
    assert retried_task.status == ExecutionTaskState.QUEUED.value
    assert dispatch is not None
    assert dispatch.status == "published"
    assert dispatch.payload_json["_runtime_queue_retry_generation"] == 1
    verify.close()

    retry_claim = queue_adapter.claim_task(tenant_id=str(tenant.id), worker_id="retry-worker")
    assert retry_claim is not None
    assert retry_claim.task_id == task.id


def test_retry_rehabilitates_current_mission_state_without_erasing_failure_evidence(
    pg_engine,
    queue_adapter: QueueAdapter,
) -> None:
    """A successful retry must supersede, not conceal, an earlier failed rollup."""

    sessions = _sessions(pg_engine)
    setup = sessions()
    tenant, task = _create_planned_task(setup, label="retry-rehabilitation")
    setup.commit()
    setup.close()

    admission = sessions()
    assert ExecutionCoordinator(admission, queue_adapter).queue_task(tenant_id=str(tenant.id), task_id=task.id).ok
    admission.commit()
    admission.close()

    first_attempt = sessions()
    runtime = WorkerRuntimeService(first_attempt, queue_adapter)
    claimed = runtime.claim_next_task(tenant_id=str(tenant.id), worker_id="initial-worker")
    assert claimed is not None
    first_lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
    runtime.start_execution(tenant_id=str(tenant.id), lease_id=first_lease_id, worker_id="initial-worker")
    runtime.fail(
        tenant_id=str(tenant.id),
        lease_id=first_lease_id,
        worker_id="initial-worker",
        reason="synthetic retryable provider failure",
    )
    first_attempt.close()

    failed_state = sessions()
    failed_task = failed_state.get(ExecutionTask, task.id)
    failed_mission = failed_state.get(Mission, task.mission_id)
    assert failed_task is not None and failed_mission is not None
    assert failed_task.status == ExecutionTaskState.FAILED.value
    assert failed_mission.status == MissionState.FAILED.value
    assert failed_task.metadata_json["failure"]["code"] == "HANDLER_FAILED"
    failed_state.close()

    retry = sessions()
    assert ExecutionCoordinator(retry, queue_adapter).retry_task(tenant_id=str(tenant.id), task_id=task.id).ok
    retry.commit()
    retry.close()

    recovered = sessions()
    retried_runtime = WorkerRuntimeService(recovered, queue_adapter)
    retried = retried_runtime.claim_next_task(tenant_id=str(tenant.id), worker_id="recovery-worker")
    assert retried is not None
    retry_lease_id = uuid.UUID(str(retried.metadata_json["worker_lease_id"]))
    retried_runtime.start_execution(tenant_id=str(tenant.id), lease_id=retry_lease_id, worker_id="recovery-worker")
    retried_runtime.complete(
        tenant_id=str(tenant.id),
        lease_id=retry_lease_id,
        worker_id="recovery-worker",
        task_output={"handler": "echo", "status": "completed", "output": {"message": "recovered"}},
    )
    recovered.close()

    verify = sessions()
    completed_task = verify.get(ExecutionTask, task.id)
    completed_mission = verify.get(Mission, task.mission_id)
    assert completed_task is not None and completed_mission is not None
    assert completed_task.status == ExecutionTaskState.COMPLETED.value
    assert "failure" not in completed_task.metadata_json
    assert completed_task.metadata_json["retry_history"][-1]["failure"]["code"] == "HANDLER_FAILED"
    assert completed_mission.status == MissionState.COMPLETED.value
    assert completed_mission.metadata_json["acceptance_history"][-1]["acceptance"]["status"] == "partially_met"
    assert completed_mission.metadata_json["runtime_recovery"]["reason"] == "governed_task_retry"
    verify.close()


def test_recovered_dependency_releases_only_blocked_descendant_through_durable_dispatch(
    pg_engine,
    queue_adapter: QueueAdapter,
) -> None:
    """A retried parent must not strand its blocked graph descendant."""

    sessions = _sessions(pg_engine)
    setup = sessions()
    tenant, parent = _create_planned_task(setup, label="retry-descendant")
    parent.metadata_json = {
        "task_type": "echo",
        "input": {"message": "parent"},
        "graph_node_key": "parent",
        "dependency_keys": [],
    }
    child = ExecutionTask(
        tenant_id=str(tenant.id),
        mission_id=parent.mission_id,
        title="dependent task",
        description="Runs only after the recovered parent succeeds",
        status=ExecutionTaskState.PLANNED.value,
        metadata_json={
            "task_type": "echo",
            "input": {"message": "child"},
            "graph_node_key": "child",
            "dependency_keys": ["parent"],
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    setup.add(child)
    setup.commit()
    setup.close()

    admission = sessions()
    assert ExecutionCoordinator(admission, queue_adapter).queue_task(tenant_id=str(tenant.id), task_id=parent.id).ok
    admission.commit()
    admission.close()

    first_attempt = sessions()
    runtime = WorkerRuntimeService(first_attempt, queue_adapter)
    claimed = runtime.claim_next_task(tenant_id=str(tenant.id), worker_id="dependency-initial-worker")
    assert claimed is not None and claimed.id == parent.id
    first_lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
    runtime.start_execution(tenant_id=str(tenant.id), lease_id=first_lease_id, worker_id="dependency-initial-worker")
    runtime.fail(
        tenant_id=str(tenant.id),
        lease_id=first_lease_id,
        worker_id="dependency-initial-worker",
        reason="synthetic parent failure",
    )
    first_attempt.close()

    blocked = sessions()
    blocked_child = blocked.get(ExecutionTask, child.id)
    assert blocked_child is not None
    assert blocked_child.status == ExecutionTaskState.BLOCKED.value
    assert blocked_child.metadata_json["blocked_by_dependency_failure"] == ["parent"]
    blocked.close()

    retry = sessions()
    assert ExecutionCoordinator(retry, queue_adapter).retry_task(tenant_id=str(tenant.id), task_id=parent.id).ok
    retry.commit()
    retry.close()

    recovered_parent = sessions()
    recovered_runtime = WorkerRuntimeService(recovered_parent, queue_adapter)
    retried_parent = recovered_runtime.claim_next_task(tenant_id=str(tenant.id), worker_id="dependency-recovery-worker")
    assert retried_parent is not None and retried_parent.id == parent.id
    retry_lease_id = uuid.UUID(str(retried_parent.metadata_json["worker_lease_id"]))
    recovered_runtime.start_execution(
        tenant_id=str(tenant.id), lease_id=retry_lease_id, worker_id="dependency-recovery-worker"
    )
    recovered_runtime.complete(
        tenant_id=str(tenant.id),
        lease_id=retry_lease_id,
        worker_id="dependency-recovery-worker",
        task_output={"handler": "echo", "status": "completed", "output": {"message": "parent recovered"}},
    )
    recovered_parent.close()

    released = sessions()
    released_child = released.get(ExecutionTask, child.id)
    assert released_child is not None
    assert released_child.status == ExecutionTaskState.QUEUED.value
    assert "failure" not in released_child.metadata_json
    assert released_child.metadata_json["dependency_block_history"][-1]["failure"]["code"] == "DEPENDENCY_FAILED"
    child_dispatch = released.scalar(select(RuntimeQueueDispatch).where(RuntimeQueueDispatch.task_id == child.id))
    assert child_dispatch is not None and child_dispatch.status == "published"
    released.close()

    finish = sessions()
    finish_runtime = WorkerRuntimeService(finish, queue_adapter)
    claimed_child = finish_runtime.claim_next_task(tenant_id=str(tenant.id), worker_id="dependency-child-worker")
    assert claimed_child is not None and claimed_child.id == child.id
    child_lease_id = uuid.UUID(str(claimed_child.metadata_json["worker_lease_id"]))
    finish_runtime.start_execution(
        tenant_id=str(tenant.id), lease_id=child_lease_id, worker_id="dependency-child-worker"
    )
    finish_runtime.complete(
        tenant_id=str(tenant.id),
        lease_id=child_lease_id,
        worker_id="dependency-child-worker",
        task_output={"handler": "echo", "status": "completed", "output": {"message": "child complete"}},
    )
    finish.close()

    verify = sessions()
    mission = verify.get(Mission, parent.mission_id)
    assert mission is not None and mission.status == MissionState.COMPLETED.value
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
