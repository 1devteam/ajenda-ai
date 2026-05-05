"""Runtime Maintainer — bounded recovery for expired leases and stale work.

Recovery path (with 'recovering' state from migration 0004):

  1. Find all WorkerLeases in CLAIMED or ACTIVE state whose heartbeat_at
     is older than expiry_seconds (default: 60s).
  2. Use the queue adapter as the runtime authority to either reconcile the
     payload back to exactly one pending message or move it to dead-letter.
  3. Transition the lease: CLAIMED/ACTIVE → EXPIRED
  4. Transition the task:
       running → recovering  (signals that recovery is in progress)
       recovering → queued   (re-enqueue for pickup by a healthy worker)
     For tasks in CLAIMED state (worker died before starting):
       claimed → queued      (direct re-queue, no recovering intermediate)
  5. Persist the bounded control-plane operation and write an AuditEvent.

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
from backend.queue.base import QueueAdapter
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.runtime.transitions import transition_lease, transition_task

logger = logging.getLogger("ajenda.runtime_maintainer")

DEFAULT_MAX_RETRIES: int = 3


@dataclass(frozen=True, slots=True)
class RecoverySummary:
    expired_lease_count: int
    requeued_task_count: int
    dead_lettered_count: int
    mismatched_state_count: int = 0


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
        tasks, dead-lettered tasks, and claimed-task/active-lease mismatches.
        """
        threshold = datetime.now(UTC) - timedelta(seconds=self._expiry_seconds)

        stmt = (
            select(WorkerLease, ExecutionTask)
            .join(ExecutionTask, WorkerLease.task_id == ExecutionTask.id)
            .where(
                WorkerLease.status.in_(
                    [
                        WorkerLeaseState.CLAIMED.value,
                        WorkerLeaseState.ACTIVE.value,
                    ]
                ),
                WorkerLease.heartbeat_at.is_not(None),
                WorkerLease.heartbeat_at < threshold,
            )
        )

        expired_count = 0
        requeued_count = 0
        dead_lettered_count = 0
        mismatched_state_count = 0

        for lease, task in self._session.execute(stmt).all():
            try:
                original_task_status = task.status
                original_lease_status = lease.status

                if (
                    original_task_status == ExecutionTaskState.CLAIMED.value
                    and original_lease_status == WorkerLeaseState.ACTIVE.value
                ):
                    mismatched_state_count += 1
                    logger.warning(
                        "runtime_maintainer_claimed_task_active_lease_mismatch",
                        extra={
                            "lease_id": str(lease.id),
                            "task_id": str(task.id),
                            "tenant_id": task.tenant_id,
                            "task_status": original_task_status,
                            "lease_status": original_lease_status,
                        },
                    )

                logger.info(
                    "runtime_maintainer_lease_expired",
                    extra={
                        "lease_id": str(lease.id),
                        "task_id": str(task.id),
                        "tenant_id": task.tenant_id,
                        "task_status": original_task_status,
                        "lease_status": original_lease_status,
                        "heartbeat_age_seconds": (datetime.now(UTC) - lease.heartbeat_at).total_seconds(),
                    },
                )

                retry_count = task.retry_count
                should_dead_letter = retry_count >= self._max_retries

                if task.status == ExecutionTaskState.RUNNING.value:
                    if should_dead_letter:
                        result = self._queue.move_to_dead_letter(
                            tenant_id=task.tenant_id,
                            task_id=task.id,
                            reason=f"max retries exceeded during recovery ({retry_count}/{self._max_retries})",
                        )
                        if not result.ok:
                            raise RuntimeError(
                                f"runtime maintainer failed to move task {task.id} to dead-letter: {result.reason}"
                            )

                        transition_lease(lease, WorkerLeaseState.EXPIRED)
                        expired_count += 1
                        transition_task(task, ExecutionTaskState.RECOVERING)
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
                        result = self._queue.recover_task_for_retry(
                            tenant_id=task.tenant_id,
                            task_id=task.id,
                            worker_id=lease.holder_identity,
                        )
                        if not result.ok:
                            raise RuntimeError(
                                f"runtime maintainer failed to reconcile task {task.id} for retry: {result.reason}"
                            )

                        transition_lease(lease, WorkerLeaseState.EXPIRED)
                        expired_count += 1
                        transition_task(task, ExecutionTaskState.RECOVERING)
                        task.retry_count = retry_count + 1
                        transition_task(task, ExecutionTaskState.QUEUED)
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
                    if should_dead_letter:
                        result = self._queue.move_to_dead_letter(
                            tenant_id=task.tenant_id,
                            task_id=task.id,
                            reason=f"max retries exceeded during claimed recovery ({retry_count}/{self._max_retries})",
                        )
                        if not result.ok:
                            raise RuntimeError(
                                f"runtime maintainer failed to move claimed task {task.id} to dead-letter: {result.reason}"
                            )

                        transition_lease(lease, WorkerLeaseState.EXPIRED)
                        expired_count += 1
                        transition_task(task, ExecutionTaskState.DEAD_LETTERED)
                        dead_lettered_count += 1
                        self._audit.append(
                            AuditEvent(
                                tenant_id=task.tenant_id,
                                mission_id=task.mission_id,
                                category="runtime_recovery",
                                action="claimed_task_dead_lettered_max_retries",
                                actor="runtime_maintainer",
                                details=(
                                    f"Expired claimed lease {lease.id}: task {task.id} dead-lettered after "
                                    f"{retry_count} retries without starting."
                                ),
                                payload_json={
                                    "task_id": str(task.id),
                                    "lease_id": str(lease.id),
                                    "retry_count": retry_count,
                                },
                            )
                        )
                    else:
                        result = self._queue.recover_task_for_retry(
                            tenant_id=task.tenant_id,
                            task_id=task.id,
                            worker_id=lease.holder_identity,
                        )
                        if not result.ok:
                            raise RuntimeError(
                                f"runtime maintainer failed to reconcile claimed task {task.id} for retry: {result.reason}"
                            )

                        transition_lease(lease, WorkerLeaseState.EXPIRED)
                        expired_count += 1
                        task.retry_count = retry_count + 1
                        transition_task(task, ExecutionTaskState.QUEUED)
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
                                    f"but never started. Re-queued directly (claimed→queued). "
                                    f"Retry {retry_count + 1}/{self._max_retries}."
                                ),
                                payload_json={
                                    "task_id": str(task.id),
                                    "lease_id": str(lease.id),
                                    "retry_count": retry_count,
                                },
                            )
                        )

                self._session.flush()
                self._session.commit()
            except Exception:
                self._session.rollback()
                raise

        logger.info(
            "runtime_maintainer_recovery_complete",
            extra={
                "expired_leases": expired_count,
                "requeued_tasks": requeued_count,
                "dead_lettered_tasks": dead_lettered_count,
                "mismatched_states": mismatched_state_count,
            },
        )

        return RecoverySummary(
            expired_lease_count=expired_count,
            requeued_task_count=requeued_count,
            dead_lettered_count=dead_lettered_count,
            mismatched_state_count=mismatched_state_count,
        )
