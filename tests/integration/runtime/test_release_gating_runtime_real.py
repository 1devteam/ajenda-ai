from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueOperationResult
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.runtime_maintainer import RuntimeMaintainer
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers import task_dispatcher as task_dispatcher_module
from backend.workers.task_dispatcher import TaskDispatcher

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


def _create_task(
    pg_session,
    tenant_id: str,
    *,
    status: ExecutionTaskState = ExecutionTaskState.PLANNED,
    **kwargs,
) -> ExecutionTask:
    mission = Mission(tenant_id=tenant_id, objective="RG mission", status="running")
    pg_session.add(mission)
    pg_session.flush()
    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=mission.id,
        title=kwargs.get("title", "RG task"),
        description=kwargs.get("description", "RG task description"),
        status=status.value,
        metadata_json=kwargs.get("metadata_json", {}),
        compliance_category=kwargs.get("compliance_category", "operational"),
        jurisdiction=kwargs.get("jurisdiction", "US-ALL"),
        requires_human_review=kwargs.get("requires_human_review", False),
    )
    pg_session.add(task)
    pg_session.flush()
    return task


def _audit_actions(pg_session, tenant_id: str) -> list[str]:
    rows = pg_session.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)).all()
    return [row.action for row in rows]


def test_rg_queue_admission_end_to_end(pg_session, queue_adapter, redis_client) -> None:
    tenant_id = str(uuid.uuid4())
    _create_tenant(pg_session, tenant_id)
    task = _create_task(pg_session, tenant_id)

    QuotaEnforcementService(pg_session).check_and_record_task_creation(uuid.UUID(tenant_id))
    result = ExecutionCoordinator(pg_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task.id)
    pg_session.flush()

    assert result.ok is True
    pg_session.refresh(task)
    assert task.status == ExecutionTaskState.QUEUED.value

    pending_len = redis_client.llen(f"ajenda:queue:{tenant_id}:pending")
    assert pending_len >= 1
    assert "queued" in _audit_actions(pg_session, tenant_id)


def test_rg_queue_interruption_rolls_back_authoritative_state(
    pg_session,
    queue_adapter,
    monkeypatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    _create_tenant(pg_session, tenant_id)
    task = _create_task(pg_session, tenant_id)

    QuotaEnforcementService(pg_session).check_and_record_task_creation(uuid.UUID(tenant_id))

    def interrupted_enqueue(*args, **kwargs) -> QueueOperationResult:
        return QueueOperationResult(ok=False, reason="redis unavailable during enqueue")

    monkeypatch.setattr(queue_adapter, "enqueue_task", interrupted_enqueue)

    coordinator = ExecutionCoordinator(pg_session, queue_adapter)
    with pytest.raises(ValueError, match="redis unavailable during enqueue"):
        coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    pg_session.refresh(task)
    actions = _audit_actions(pg_session, tenant_id)

    assert task.status == ExecutionTaskState.PLANNED.value
    assert task.retry_count == 0
    assert "queued" not in actions
    assert "task_pending_review" not in actions


def test_rg_happy_execution_flow(pg_session, queue_adapter, redis_client) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-rg-happy"
    _create_tenant(pg_session, tenant_id)
    task = _create_task(pg_session, tenant_id)

    QuotaEnforcementService(pg_session).check_and_record_task_creation(uuid.UUID(tenant_id))
    ExecutionCoordinator(pg_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task.id)

    runtime = WorkerRuntimeService(pg_session, queue_adapter)
    claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
    assert claimed is not None

    lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
    runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
    runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
    completed = runtime.complete(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
    pg_session.flush()

    assert completed.status == ExecutionTaskState.COMPLETED.value
    lease = pg_session.get(WorkerLease, lease_id)
    assert lease is not None
    assert lease.status == WorkerLeaseState.RELEASED.value
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
    assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task.id}") is None
    assert "task_completed" in _audit_actions(pg_session, tenant_id)


def test_rg_long_running_dispatcher_maintains_midflight_heartbeat(
    pg_engine,
    queue_adapter,
    monkeypatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-rg-long-running"
    task_type = "slow_success"
    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    setup_session = session_factory()
    try:
        _create_tenant(setup_session, tenant_id)
        task = _create_task(setup_session, tenant_id, metadata_json={"task_type": task_type})
        task_id = task.id

        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_id))
        ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task_id)

        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None

        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup_session.commit()

        initial_lease = setup_session.get(WorkerLease, lease_id)
        assert initial_lease is not None
        initial_heartbeat_at = initial_lease.heartbeat_at
        assert initial_heartbeat_at is not None
    finally:
        setup_session.close()

    handler_started = threading.Event()
    handler_release = threading.Event()

    def slow_success_handler(task: ExecutionTask, context: dict[str, object]) -> dict[str, str]:
        handler_started.set()
        if not handler_release.wait(timeout=5.0):
            raise TimeoutError("slow_success handler timed out waiting for release signal")
        return {"status": "completed", "handler": "slow_success"}

    monkeypatch.setitem(task_dispatcher_module._HANDLER_REGISTRY, task_type, slow_success_handler)
    monkeypatch.setattr(task_dispatcher_module, "_HEARTBEAT_INTERVAL", 0.05)

    dispatcher = TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    )
    dispatch_thread = threading.Thread(
        target=dispatcher.execute,
        kwargs={"task_id": task_id, "lease_id": lease_id},
        daemon=True,
        name="dispatch-slow-success",
    )
    dispatch_thread.start()

    assert handler_started.wait(timeout=2.0)
    time.sleep(0.2)

    midflight_session = session_factory()
    try:
        midflight_task = midflight_session.get(ExecutionTask, task_id)
        midflight_lease = midflight_session.get(WorkerLease, lease_id)
        assert midflight_task is not None
        assert midflight_lease is not None
        assert midflight_task.status == ExecutionTaskState.RUNNING.value
        assert midflight_lease.status == WorkerLeaseState.ACTIVE.value
        assert midflight_lease.heartbeat_at is not None
        assert midflight_lease.heartbeat_at > initial_heartbeat_at
    finally:
        midflight_session.close()

    handler_release.set()
    dispatch_thread.join(timeout=5.0)
    assert not dispatch_thread.is_alive()

    final_session = session_factory()
    try:
        final_task = final_session.get(ExecutionTask, task_id)
        final_lease = final_session.get(WorkerLease, lease_id)
        assert final_task is not None
        assert final_lease is not None
        assert final_task.status == ExecutionTaskState.COMPLETED.value
        assert final_lease.status == WorkerLeaseState.RELEASED.value
        actions = _audit_actions(final_session, tenant_id)
        assert "task_completed" in actions
        assert "task_failed" not in actions
    finally:
        final_session.close()


def test_rg_started_work_interrupted_before_completion_recovers_safely(
    pg_session,
    queue_adapter,
    redis_client,
) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-rg-interrupted"
    _create_tenant(pg_session, tenant_id)
    task = _create_task(pg_session, tenant_id)

    QuotaEnforcementService(pg_session).check_and_record_task_creation(uuid.UUID(tenant_id))
    ExecutionCoordinator(pg_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task.id)

    runtime = WorkerRuntimeService(pg_session, queue_adapter)
    claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
    assert claimed is not None

    lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
    runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
    started = runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
    assert started.status == ExecutionTaskState.RUNNING.value

    lease = pg_session.get(WorkerLease, lease_id)
    assert lease is not None
    lease.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
    pg_session.flush()

    summary = RuntimeMaintainer(pg_session, queue_adapter, expiry_seconds=30, max_retries=3).recover_expired_leases()
    pg_session.flush()

    pg_session.refresh(task)
    pg_session.refresh(lease)
    actions = _audit_actions(pg_session, tenant_id)

    assert summary.expired_lease_count == 1
    assert summary.requeued_task_count == 1
    assert summary.dead_lettered_count == 0
    assert task.status == ExecutionTaskState.QUEUED.value
    assert task.retry_count == 1
    assert lease.status == WorkerLeaseState.EXPIRED.value
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:pending") >= 1
    assert "lease_expired_task_requeued" in actions
    assert "task_completed" not in actions
    assert "task_failed" not in actions


def test_rg_duplicate_completion_rejected_without_processing_regression(
    pg_session,
    queue_adapter,
    redis_client,
) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-rg-duplicate-complete"
    _create_tenant(pg_session, tenant_id)
    task = _create_task(pg_session, tenant_id)

    QuotaEnforcementService(pg_session).check_and_record_task_creation(uuid.UUID(tenant_id))
    ExecutionCoordinator(pg_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task.id)

    runtime = WorkerRuntimeService(pg_session, queue_adapter)
    claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
    assert claimed is not None

    lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
    runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
    runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
    runtime.complete(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
    pg_session.flush()

    first_completed_audit_count = len(
        [action for action in _audit_actions(pg_session, tenant_id) if action == "task_completed"]
    )

    with pytest.raises(ValueError, match="task is not running"):
        runtime.complete(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)

    pg_session.refresh(task)
    lease = pg_session.get(WorkerLease, lease_id)
    assert lease is not None

    second_completed_audit_count = len(
        [action for action in _audit_actions(pg_session, tenant_id) if action == "task_completed"]
    )

    assert task.status == ExecutionTaskState.COMPLETED.value
    assert lease.status == WorkerLeaseState.RELEASED.value
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
    assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task.id}") is None
    assert first_completed_audit_count == 1
    assert second_completed_audit_count == 1


def test_rg_forced_failure_path(pg_session, queue_adapter, redis_client) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-rg-fail"
    _create_tenant(pg_session, tenant_id)
    task = _create_task(pg_session, tenant_id, metadata_json={"task_type": "force_fail"})

    QuotaEnforcementService(pg_session).check_and_record_task_creation(uuid.UUID(tenant_id))
    ExecutionCoordinator(pg_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task.id)

    runtime = WorkerRuntimeService(pg_session, queue_adapter)
    claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
    assert claimed is not None
    lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
    runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
    failed = runtime.fail(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id, reason="forced failure")
    pg_session.flush()

    assert failed.status == ExecutionTaskState.FAILED.value
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:dead_letter") >= 1
    assert "task_failed" in _audit_actions(pg_session, tenant_id)


def test_rg_claimed_recovery(pg_session, queue_adapter, redis_client) -> None:
    tenant_id = str(uuid.uuid4())
    _create_tenant(pg_session, tenant_id)
    task = _create_task(pg_session, tenant_id, status=ExecutionTaskState.CLAIMED)
    lease = WorkerLease(
        tenant_id=tenant_id,
        task_id=task.id,
        holder_identity="worker-stale",
        status=WorkerLeaseState.CLAIMED.value,
        heartbeat_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    pg_session.add(lease)
    pg_session.flush()

    summary = RuntimeMaintainer(pg_session, queue_adapter, expiry_seconds=30).recover_expired_leases()
    pg_session.flush()

    assert summary.expired_lease_count == 1
    assert summary.requeued_task_count == 1
    pg_session.refresh(task)
    pg_session.refresh(lease)
    assert task.status == ExecutionTaskState.QUEUED.value
    assert lease.status == WorkerLeaseState.EXPIRED.value
    assert "claimed_task_requeued_on_lease_expiry" in _audit_actions(pg_session, tenant_id)


def test_rg_running_recovery_and_retry_exhaustion(pg_session, queue_adapter) -> None:
    tenant_id = str(uuid.uuid4())
    _create_tenant(pg_session, tenant_id)

    requeue_task = _create_task(pg_session, tenant_id, status=ExecutionTaskState.RUNNING)
    exhaust_task = _create_task(pg_session, tenant_id, status=ExecutionTaskState.RUNNING)
    exhaust_task.retry_count = 3

    stale_a = WorkerLease(
        tenant_id=tenant_id,
        task_id=requeue_task.id,
        holder_identity="worker-a",
        status=WorkerLeaseState.ACTIVE.value,
        heartbeat_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    stale_b = WorkerLease(
        tenant_id=tenant_id,
        task_id=exhaust_task.id,
        holder_identity="worker-b",
        status=WorkerLeaseState.ACTIVE.value,
        heartbeat_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    pg_session.add_all([stale_a, stale_b])
    pg_session.flush()

    summary = RuntimeMaintainer(pg_session, queue_adapter, expiry_seconds=30, max_retries=3).recover_expired_leases()
    pg_session.flush()

    pg_session.refresh(requeue_task)
    pg_session.refresh(exhaust_task)
    assert summary.expired_lease_count == 2
    assert requeue_task.status == ExecutionTaskState.QUEUED.value
    assert requeue_task.retry_count == 1
    assert exhaust_task.status == ExecutionTaskState.DEAD_LETTERED.value


def test_rg_recovery_safety_only_stale_mutates(pg_session, queue_adapter) -> None:
    tenant_id = str(uuid.uuid4())
    _create_tenant(pg_session, tenant_id)

    stale = _create_task(pg_session, tenant_id, status=ExecutionTaskState.CLAIMED)
    healthy = _create_task(pg_session, tenant_id, status=ExecutionTaskState.RUNNING)

    stale_lease = WorkerLease(
        tenant_id=tenant_id,
        task_id=stale.id,
        holder_identity="worker-stale",
        status=WorkerLeaseState.ACTIVE.value,
        heartbeat_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    healthy_lease = WorkerLease(
        tenant_id=tenant_id,
        task_id=healthy.id,
        holder_identity="worker-healthy",
        status=WorkerLeaseState.ACTIVE.value,
        heartbeat_at=datetime.now(UTC) - timedelta(seconds=5),
    )
    pg_session.add_all([stale_lease, healthy_lease])
    pg_session.flush()

    RuntimeMaintainer(pg_session, queue_adapter, expiry_seconds=60).recover_expired_leases()
    pg_session.flush()

    pg_session.refresh(stale)
    pg_session.refresh(healthy)
    pg_session.refresh(stale_lease)
    pg_session.refresh(healthy_lease)

    assert stale.status == ExecutionTaskState.QUEUED.value
    assert stale_lease.status == WorkerLeaseState.EXPIRED.value
    assert healthy.status == ExecutionTaskState.RUNNING.value
    assert healthy_lease.status == WorkerLeaseState.ACTIVE.value


def test_rg_duplicate_active_lease_claim_rejected_with_queue_compensation(
    pg_session,
    queue_adapter,
    redis_client,
) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-duplicate-claim"
    _create_tenant(pg_session, tenant_id)
    task = _create_task(pg_session, tenant_id)

    QuotaEnforcementService(pg_session).check_and_record_task_creation(uuid.UUID(tenant_id))
    ExecutionCoordinator(pg_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task.id)

    existing_lease = WorkerLease(
        tenant_id=tenant_id,
        task_id=task.id,
        holder_identity="worker-existing",
        status=WorkerLeaseState.ACTIVE.value,
        heartbeat_at=datetime.now(UTC),
    )
    pg_session.add(existing_lease)
    pg_session.flush()

    runtime = WorkerRuntimeService(pg_session, queue_adapter)
    with pytest.raises(ValueError, match="task already has an active lease"):
        runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)

    pg_session.refresh(task)
    leases = pg_session.scalars(
        select(WorkerLease).where(
            WorkerLease.tenant_id == tenant_id,
            WorkerLease.task_id == task.id,
        )
    ).all()

    assert task.status == ExecutionTaskState.QUEUED.value
    assert len(leases) == 1
    assert leases[0].id == existing_lease.id
    assert leases[0].status == WorkerLeaseState.ACTIVE.value
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:pending") >= 1
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
    assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task.id}") is None


def test_rg_pending_review_policy_gate(pg_session, queue_adapter, redis_client) -> None:
    tenant_id = str(uuid.uuid4())
    _create_tenant(pg_session, tenant_id)
    task = _create_task(
        pg_session,
        tenant_id,
        compliance_category="employment",
        jurisdiction="US-NY",
        requires_human_review=False,
        metadata_json={},
    )

    QuotaEnforcementService(pg_session).check_and_record_task_creation(uuid.UUID(tenant_id))
    result = ExecutionCoordinator(pg_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task.id)
    pg_session.flush()

    assert result.ok is False
    pg_session.refresh(task)
    assert task.status == ExecutionTaskState.PENDING_REVIEW.value
    assert task.requires_human_review is True
    assert redis_client.llen(f"ajenda:queue:{tenant_id}:pending") == 0

    actions = _audit_actions(pg_session, tenant_id)
    assert "task_pending_review" in actions
