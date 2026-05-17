from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueAdapter, QueueMessage
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.runtime.transitions import transition_lease, transition_task


@dataclass(frozen=True, slots=True)
class RecoverySummary:
    expired_lease_count: int
    requeued_task_count: int


class RuntimeMaintainer:
    """Bounded recovery for expired leases and stale claimed/running work.

    Recovery ownership rule:
    - Runtime recovery marks stale DB leases EXPIRED.
    - Worker-owned normal cleanup marks DB leases RELEASED.
    - Queue enqueue/recovery behavior remains separate from DB lease state.
    """

    def __init__(self, session: Session, queue: QueueAdapter, expiry_seconds: int = 60) -> None:
        self._session = session
        self._queue = queue
        self._expiry_seconds = expiry_seconds
        self._audit = AuditEventRepository(session)

    def recover_expired_leases(self) -> RecoverySummary:
        threshold = datetime.now(UTC) - timedelta(seconds=self._expiry_seconds)
        stmt = (
            select(WorkerLease, ExecutionTask)
            .join(
                ExecutionTask,
                WorkerLease.task_id == ExecutionTask.id,
            )
            .where(
                WorkerLease.status.in_(
                    [WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value]
                ),
                WorkerLease.heartbeat_at.is_not(None),
                WorkerLease.heartbeat_at < threshold,
            )
        )

        expired_count = 0
        requeued_count = 0

        for lease, task in self._session.execute(stmt).all():
            transition_lease(lease, WorkerLeaseState.EXPIRED)
            expired_count += 1

            if task.status == ExecutionTaskState.RUNNING.value:
                transition_task(task, ExecutionTaskState.RECOVERING)
                transition_task(task, ExecutionTaskState.QUEUED)
                self._enqueue_recovered_task(task)
                requeued_count += 1
                self._append_recovery_audit(
                    lease=lease,
                    task=task,
                    action="running_task_recovered",
                    details=(
                        f"Expired lease {lease.id} caused running task {task.id} "
                        "to recover through running->recovering->queued."
                    ),
                )

            elif task.status == ExecutionTaskState.CLAIMED.value:
                transition_task(task, ExecutionTaskState.QUEUED)
                self._enqueue_recovered_task(task)
                requeued_count += 1
                self._append_recovery_audit(
                    lease=lease,
                    task=task,
                    action="claimed_task_requeued_on_lease_expiry",
                    details=(
                        f"Expired lease {lease.id} caused claimed task {task.id} "
                        "to be requeued directly."
                    ),
                )

        self._session.flush()
        return RecoverySummary(
            expired_lease_count=expired_count,
            requeued_task_count=requeued_count,
        )

    def _enqueue_recovered_task(self, task: ExecutionTask) -> None:
        self._queue.enqueue_task(
            QueueMessage(
                tenant_id=task.tenant_id,
                task_id=task.id,
                mission_id=task.mission_id,
                fleet_id=task.fleet_id,
                branch_id=task.branch_id,
                payload=task.metadata_json,
                enqueued_at=datetime.now(UTC),
            )
        )

    def _append_recovery_audit(
        self,
        *,
        lease: WorkerLease,
        task: ExecutionTask,
        action: str,
        details: str,
    ) -> None:
        self._audit.append(
            AuditEvent(
                tenant_id=task.tenant_id,
                mission_id=task.mission_id,
                category="runtime_recovery",
                action=action,
                actor="runtime_maintainer",
                details=details,
                payload_json={"task_id": str(task.id), "lease_id": str(lease.id)},
            )
        )
