"""Integration test: lease recovery against real Postgres and Redis.

Replaces the mock-based test_lease_recovery.py which could not catch:
- The non-atomic Redis/Postgres claim gap (CRITICAL-003)
- The running→recovering→queued state transition sequence
- Real Redis LMOVE behavior vs mocked enqueue
- Actual heartbeat timestamp comparison in Postgres

This test requires Docker (via testcontainers). It is marked with
pytest.mark.integration and skipped in unit test runs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueMessage
from backend.services.runtime_maintainer import RuntimeMaintainer

pytestmark = pytest.mark.integration


def _make_mission(tenant_id: str) -> Mission:
    return Mission(
        tenant_id=tenant_id,
        objective="Integration test mission",
        status="running",
    )


def _make_task(tenant_id: str, mission_id, status: str) -> ExecutionTask:
    return ExecutionTask(
        tenant_id=tenant_id,
        mission_id=mission_id,
        title="Integration test task",
        description="Test task for lease recovery",
        status=status,
    )


def _make_expired_lease(
    task_id,
    tenant_id: str,
    worker_id: str = "worker-dead",
) -> WorkerLease:
    """Create a lease with a heartbeat 10 minutes in the past (expired)."""
    return WorkerLease(
        tenant_id=tenant_id,
        task_id=task_id,
        holder_identity=worker_id,
        status=WorkerLeaseState.ACTIVE.value,
        heartbeat_at=datetime.now(UTC) - timedelta(minutes=10),
    )


def _prime_processing_payload(queue_adapter, tenant_id: str, task_id, mission_id, worker_id: str) -> None:
    message = QueueMessage(
        tenant_id=tenant_id,
        task_id=task_id,
        mission_id=mission_id,
        fleet_id=None,
        branch_id=None,
        payload={},
        enqueued_at=datetime.now(UTC),
    )
    enqueue_result = queue_adapter.enqueue_task(message)
    assert enqueue_result.ok is True
    claimed = queue_adapter.claim_task(tenant_id=tenant_id, worker_id=worker_id)
    assert claimed is not None
    assert claimed.task_id == task_id


class TestLeaseRecoveryReal:
    def test_running_task_transitions_through_recovering_to_queued(
        self,
        pg_session,
        queue_adapter,
    ) -> None:
        """A running task with an expired lease must go running→recovering→queued."""
        mission = _make_mission("tenant-recovery-a")
        pg_session.add(mission)
        pg_session.flush()

        task = _make_task("tenant-recovery-a", mission.id, ExecutionTaskState.RUNNING.value)
        pg_session.add(task)
        pg_session.flush()

        lease = _make_expired_lease(task.id, "tenant-recovery-a")
        pg_session.add(lease)
        pg_session.flush()
        _prime_processing_payload(queue_adapter, task.tenant_id, task.id, mission.id, lease.holder_identity)

        maintainer = RuntimeMaintainer(
            session=pg_session,
            queue=queue_adapter,
            expiry_seconds=30,  # 10-minute-old heartbeat is well past this
            max_retries=3,
        )
        summary = maintainer.recover_expired_leases()

        assert summary.expired_lease_count == 1
        assert summary.requeued_task_count == 1
        assert summary.dead_lettered_count == 0

        # Verify the task is now QUEUED (not RUNNING or RECOVERING)
        pg_session.refresh(task)
        assert task.status == ExecutionTaskState.QUEUED.value

        # Verify the lease is now EXPIRED
        pg_session.refresh(lease)
        assert lease.status == WorkerLeaseState.EXPIRED.value

    def test_claimed_task_requeued_directly_without_recovering(self, pg_session, queue_adapter) -> None:
        """A claimed task (never started) must go directly claimed→queued."""
        mission = _make_mission("tenant-recovery-b")
        pg_session.add(mission)
        pg_session.flush()

        task = _make_task("tenant-recovery-b", mission.id, ExecutionTaskState.CLAIMED.value)
        pg_session.add(task)
        pg_session.flush()

        lease = _make_expired_lease(task.id, "tenant-recovery-b")
        pg_session.add(lease)
        pg_session.flush()
        _prime_processing_payload(queue_adapter, task.tenant_id, task.id, mission.id, lease.holder_identity)

        maintainer = RuntimeMaintainer(
            session=pg_session,
            queue=queue_adapter,
            expiry_seconds=30,
            max_retries=3,
        )
        summary = maintainer.recover_expired_leases()

        assert summary.expired_lease_count == 1
        assert summary.requeued_task_count == 1

        pg_session.refresh(task)
        assert task.status == ExecutionTaskState.QUEUED.value

    def test_healthy_lease_not_recovered(self, pg_session, queue_adapter) -> None:
        """A lease with a recent heartbeat must not be expired or recovered."""
        mission = _make_mission("tenant-recovery-c")
        pg_session.add(mission)
        pg_session.flush()

        task = _make_task("tenant-recovery-c", mission.id, ExecutionTaskState.RUNNING.value)
        pg_session.add(task)
        pg_session.flush()

        # Healthy lease — heartbeat 5 seconds ago
        healthy_lease = WorkerLease(
            tenant_id="tenant-recovery-c",
            task_id=task.id,
            holder_identity="worker-alive",
            status=WorkerLeaseState.ACTIVE.value,
            heartbeat_at=datetime.now(UTC) - timedelta(seconds=5),
        )
        pg_session.add(healthy_lease)
        pg_session.flush()

        maintainer = RuntimeMaintainer(
            session=pg_session,
            queue=queue_adapter,
            expiry_seconds=60,
        )
        summary = maintainer.recover_expired_leases()

        assert summary.expired_lease_count == 0
        assert summary.requeued_task_count == 0

        pg_session.refresh(task)
        assert task.status == ExecutionTaskState.RUNNING.value

    def test_max_retries_exceeded_dead_letters_task(self, pg_session, queue_adapter) -> None:
        """A task that has exceeded max_retries must be dead-lettered, not re-queued."""
        mission = _make_mission("tenant-recovery-d")
        pg_session.add(mission)
        pg_session.flush()

        task = _make_task("tenant-recovery-d", mission.id, ExecutionTaskState.RUNNING.value)
        # Use the typed retry_count column (migration 0008), not metadata_json.
        # RuntimeMaintainer reads task.retry_count directly.
        task.retry_count = 3  # Already at max_retries=3
        pg_session.add(task)
        pg_session.flush()

        lease = _make_expired_lease(task.id, "tenant-recovery-d")
        pg_session.add(lease)
        pg_session.flush()

        maintainer = RuntimeMaintainer(
            session=pg_session,
            queue=queue_adapter,
            expiry_seconds=30,
            max_retries=3,
        )
        summary = maintainer.recover_expired_leases()

        assert summary.expired_lease_count == 1
        assert summary.requeued_task_count == 0
        assert summary.dead_lettered_count == 1

        pg_session.refresh(task)
        assert task.status == ExecutionTaskState.DEAD_LETTERED.value

    def test_repeated_recovery_does_not_requeue_or_mutate_already_resolved_work(
        self,
        pg_session,
        queue_adapter,
    ) -> None:
        """A second recovery run must not re-enqueue or re-mutate the same recovered task."""
        mission = _make_mission("tenant-recovery-e")
        pg_session.add(mission)
        pg_session.flush()

        task = _make_task("tenant-recovery-e", mission.id, ExecutionTaskState.RUNNING.value)
        pg_session.add(task)
        pg_session.flush()

        lease = _make_expired_lease(task.id, "tenant-recovery-e")
        pg_session.add(lease)
        pg_session.flush()
        _prime_processing_payload(queue_adapter, task.tenant_id, task.id, mission.id, lease.holder_identity)

        maintainer = RuntimeMaintainer(
            session=pg_session,
            queue=queue_adapter,
            expiry_seconds=30,
            max_retries=3,
        )

        first_summary = maintainer.recover_expired_leases()
        first_retry_count = task.retry_count

        first_audit_count = (
            pg_session.query(AuditEvent)
            .filter(
                AuditEvent.action == "lease_expired_task_requeued",
                AuditEvent.payload_json["task_id"].astext == str(task.id),
            )
            .count()
        )

        second_summary = maintainer.recover_expired_leases()

        pg_session.refresh(task)
        pg_session.refresh(lease)

        second_audit_count = (
            pg_session.query(AuditEvent)
            .filter(
                AuditEvent.action == "lease_expired_task_requeued",
                AuditEvent.payload_json["task_id"].astext == str(task.id),
            )
            .count()
        )

        assert first_summary.expired_lease_count == 1
        assert first_summary.requeued_task_count == 1
        assert first_summary.dead_lettered_count == 0
        assert second_summary.expired_lease_count == 0
        assert second_summary.requeued_task_count == 0
        assert second_summary.dead_lettered_count == 0

        assert task.status == ExecutionTaskState.QUEUED.value
        assert lease.status == WorkerLeaseState.EXPIRED.value
        assert task.retry_count == first_retry_count == 1
        assert first_audit_count == 1
        assert second_audit_count == 1


def test_running_recovery_restores_state_when_queue_release_fails(
    pg_engine,
    queue_adapter,
    monkeypatch,
) -> None:
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    setup_session = session_factory()
    try:
        mission = _make_mission("tenant-recovery-release-fails")
        setup_session.add(mission)
        setup_session.flush()

        task = _make_task("tenant-recovery-release-fails", mission.id, ExecutionTaskState.RUNNING.value)
        setup_session.add(task)
        setup_session.flush()

        lease = _make_expired_lease(task.id, "tenant-recovery-release-fails")
        setup_session.add(lease)
        setup_session.flush()
        _prime_processing_payload(queue_adapter, task.tenant_id, task.id, mission.id, lease.holder_identity)

        task_id = task.id
        lease_id = lease.id
        setup_session.commit()
    finally:
        setup_session.close()

    def interrupted_release(*args, **kwargs):
        from backend.queue.base import QueueOperationResult

        return QueueOperationResult(ok=False, reason="redis unavailable during recovery release")

    monkeypatch.setattr(queue_adapter, "release_lease", interrupted_release)

    recovery_session = session_factory()
    try:
        maintainer = RuntimeMaintainer(
            session=recovery_session,
            queue=queue_adapter,
            expiry_seconds=30,
            max_retries=3,
        )

        with pytest.raises(RuntimeError, match="redis unavailable during recovery release"):
            maintainer.recover_expired_leases()
    finally:
        recovery_session.close()

    verify_session = session_factory()
    try:
        recovered_task = verify_session.get(ExecutionTask, task_id)
        recovered_lease = verify_session.get(WorkerLease, lease_id)
        assert recovered_task is not None
        assert recovered_lease is not None

        audit_count = (
            verify_session.query(AuditEvent)
            .filter(
                AuditEvent.action == "lease_expired_task_requeued",
                AuditEvent.payload_json["task_id"].astext == str(task_id),
            )
            .count()
        )

        assert recovered_task.status == ExecutionTaskState.RUNNING.value
        assert recovered_task.retry_count == 0
        assert recovered_lease.status == WorkerLeaseState.ACTIVE.value
        assert audit_count == 0
    finally:
        verify_session.close()


def test_running_recovery_restores_state_when_dead_letter_move_fails(
    pg_engine,
    queue_adapter,
    monkeypatch,
) -> None:
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    setup_session = session_factory()
    try:
        mission = _make_mission("tenant-recovery-dead-letter-fails")
        setup_session.add(mission)
        setup_session.flush()

        task = _make_task("tenant-recovery-dead-letter-fails", mission.id, ExecutionTaskState.RUNNING.value)
        task.retry_count = 3
        setup_session.add(task)
        setup_session.flush()

        lease = _make_expired_lease(task.id, "tenant-recovery-dead-letter-fails")
        setup_session.add(lease)
        setup_session.flush()

        task_id = task.id
        lease_id = lease.id
        setup_session.commit()
    finally:
        setup_session.close()

    def interrupted_dead_letter(*args, **kwargs):
        from backend.queue.base import QueueOperationResult

        return QueueOperationResult(ok=False, reason="redis unavailable during recovery dead-letter")

    monkeypatch.setattr(queue_adapter, "move_to_dead_letter", interrupted_dead_letter)

    recovery_session = session_factory()
    try:
        maintainer = RuntimeMaintainer(
            session=recovery_session,
            queue=queue_adapter,
            expiry_seconds=30,
            max_retries=3,
        )

        with pytest.raises(RuntimeError, match="redis unavailable during recovery dead-letter"):
            maintainer.recover_expired_leases()
    finally:
        recovery_session.close()

    verify_session = session_factory()
    try:
        recovered_task = verify_session.get(ExecutionTask, task_id)
        recovered_lease = verify_session.get(WorkerLease, lease_id)
        assert recovered_task is not None
        assert recovered_lease is not None

        audit_count = (
            verify_session.query(AuditEvent)
            .filter(
                AuditEvent.action == "task_dead_lettered_max_retries",
                AuditEvent.payload_json["task_id"].astext == str(task_id),
            )
            .count()
        )

        assert recovered_task.status == ExecutionTaskState.RUNNING.value
        assert recovered_task.retry_count == 3
        assert recovered_lease.status == WorkerLeaseState.ACTIVE.value
        assert audit_count == 0
    finally:
        verify_session.close()
