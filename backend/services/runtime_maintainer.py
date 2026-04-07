"""Runtime Maintainer — bounded recovery for expired leases and stale work.

Recovery path (with 'recovering' state from migration 0004):

  1. Find all WorkerLeases in CLAIMED or ACTIVE state whose heartbeat_at
     is older than expiry_seconds (default: 60s).
  2. Transition the lease: CLAIMED/ACTIVE → EXPIRED
  3. Transition the task:
       running → recovering  (signals that recovery is in progress)
       recovering → queued   (re-enqueue for pickup by a healthy worker)
     For tasks in CLAIMED state (worker died before starting):
       claimed → queued      (direct re-queue, no recovering intermediate)
  4. Enqueue a new QueueMessage for the task.
  5. Write an AuditEvent for observability.

The 'recovering' intermediate state provides:
- Observability: operators can see tasks being recovered vs freshly queued
- Deduplication: prevents double-enqueue if recovery runs concurrently
- Audit trail: complete lifecycle record including failure recovery

Max retries:
  If task.retry_count >= max_retries, transition to DEAD_LETTERED instead
  of re-queuing. This prevents infinite retry loops for permanently broken tasks.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger("ajenda.runtime_maintainer")

# Default maximum number of recovery attempts before dead-lettering
DEFAULT_MAX_RETRIES: int = 3


@dataclass(frozen=True, slots=True)
class RecoverySummary:
    expired_lease_count: int
    requeued_task_count: int
    dead_lettered_count: int


class RuntimeMaintainer:
    """Bounded recovery for expired leases and stale claimed/running work.

    This service is invoked by the worker loop on a schedule (typically every
    30-60 seconds). It is idempotent: running it multiple times on the same
    expired lease produces the same result (the lease stays EXPIRED, the task
    stays QUEUED or DEAD_LETTERED).
    """

    def __init__(
        self,
        session: Session,
        queue: QueueAdapter,
        expiry_seconds: int = 60,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self._session = session
        self._queue = queue
        self._expiry_seconds = expiry_seconds
        self._max_retries = max_retries
        self._audit = AuditEventRepository(session)

    def recover_expired_leases(self) -> RecoverySummary:
        """Find expired leases and recover their associated tasks.

        Returns a RecoverySummary with counts of expired leases, re-queued
        tasks, and dead-lettered tasks.
        """
        threshold = datetime.now(UTC) - timedelta(seconds=self._expiry_seconds)

        stmt = (
            select(WorkerLease, ExecutionTask)
            .join(ExecutionTask, WorkerLease.task_id == ExecutionTask.id)
            .where(
                WorkerLease.status.in_([WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value]),
                WorkerLease.heartbeat_at.is_not(None),
                WorkerLease.heartbeat_at < threshold,
            )
        )

        expired_count = 0
        requeued_count = 0
        dead_lettered_count = 0

        for lease, task in self._session.execute(stmt).all():
            # Step 1: Expire the lease
            transition_lease(lease, WorkerLeaseState.EXPIRED)
            expired_count += 1

            logger.info(
                "runtime_maintainer_lease_expired",
                extra={
                    "lease_id": str(lease.id),
                    "task_id": str(task.id),
                    "tenant_id": task.tenant_id,
                    "task_status": task.status,
                    "heartbeat_age_seconds": (datetime.now(UTC) - lease.heartbeat_at).total_seconds(),
                },
            )

            # Step 2: Determine recovery path based on current task state
            if task.status == ExecutionTaskState.RUNNING.value:
                # Transition through 'recovering' to make the recovery visible
                transition_task(task, ExecutionTaskState.RECOVERING)

                retry_count = getattr(task, "retry_count", 0) or 0
                if retry_count >= self._max_retries:
                    # Max retries exceeded — dead-letter the task
                    transition_task(task, ExecutionTaskState.DEAD_LETTERED)
                    dead_lettered_count += 1
                    self._audit.append(
                        AuditEvent(
                            tenant_id=task.tenant_id,
                            mission_id=task.mission_id,
                            category="runtime_recovery",
                            action="task_dead_lettered_max_retries",
                            actor="runtime_maintainer",
                            details=(
                                f"Task {task.id} dead-lettered after {retry_count} retries. Expired lease: {lease.id}."
                            ),
                            payload_json={
                                "task_id": str(task.id),
                                "lease_id": str(lease.id),
                                "retry_count": retry_count,
                            },
                        )
                    )
                    logger.warning(
                        "runtime_maintainer_task_dead_lettered",
                        extra={
                            "task_id": str(task.id),
                            "retry_count": retry_count,
                            "max_retries": self._max_retries,
                        },
                    )
                else:
                    # Re-queue for pickup by a healthy worker
                    transition_task(task, ExecutionTaskState.QUEUED)
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
                    requeued_count += 1
                    self._audit.append(
                        AuditEvent(
                            tenant_id=task.tenant_id,
                            mission_id=task.mission_id,
                            category="runtime_recovery",
                            action="lease_expired_task_requeued",
                            actor="runtime_maintainer",
                            details=(
                                f"Expired lease {lease.id} caused task {task.id} to be "
                                f"recovered (running→recovering→queued). "
                                f"Retry {retry_count + 1}/{self._max_retries}."
                            ),
                            payload_json={
                                "task_id": str(task.id),
                                "lease_id": str(lease.id),
                                "retry_count": retry_count,
                            },
                        )
                    )
                    logger.info(
                        "runtime_maintainer_task_requeued",
                        extra={
                            "task_id": str(task.id),
                            "retry_count": retry_count + 1,
                        },
                    )

            elif task.status == ExecutionTaskState.CLAIMED.value:
                # Worker died before starting — direct claimed→queued re-queue
                # No 'recovering' intermediate needed (task never ran)
                transition_task(task, ExecutionTaskState.QUEUED)
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
                requeued_count += 1
                self._audit.append(
                    AuditEvent(
                        tenant_id=task.tenant_id,
                        mission_id=task.mission_id,
                        category="runtime_recovery",
                        action="claimed_task_requeued_on_lease_expiry",
                        actor="runtime_maintainer",
                        details=(
                            f"Expired lease {lease.id}: task {task.id} was claimed "
                            f"but never started. Re-queued directly (claimed→queued)."
                        ),
                        payload_json={
                            "task_id": str(task.id),
                            "lease_id": str(lease.id),
                        },
                    )
                )

        self._session.flush()

        logger.info(
            "runtime_maintainer_recovery_complete",
            extra={
                "expired_leases": expired_count,
                "requeued_tasks": requeued_count,
                "dead_lettered_tasks": dead_lettered_count,
            },
        )

        return RecoverySummary(
            expired_lease_count=expired_count,
            requeued_task_count=requeued_count,
            dead_lettered_count=dead_lettered_count,
        )
