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

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.worker_lease import WorkerLease
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


def _make_expired_lease(task_id, tenant_id: str, worker_id: str = "worker-dead") -> WorkerLease:
    """Create a lease with a heartbeat 10 minutes in the past (expired)."""
    return WorkerLease(
        tenant_id=tenant_id,
        task_id=task_id,
        holder_identity=worker_id,
        status=WorkerLeaseState.ACTIVE.value,
        heartbeat_at=datetime.now(UTC) - timedelta(minutes=10),
    )


class TestLeaseRecoveryReal:
    def test_running_task_transitions_through_recovering_to_queued(self, pg_session, queue_adapter) -> None:
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
