"""Worker Runtime Service — manages task claim, execution, heartbeat, and completion.

Atomicity fix: The previous implementation performed a Redis claim followed by
a PostgreSQL lease creation as two separate, non-atomic operations. A crash
between them would leave the task claimed in Redis but with no DB lease,
permanently losing the task with no recovery path.

This implementation:
- Claims from queue first (Redis)
- Creates the DB lease in a try/except
- On DB failure, releases the Redis claim (compensation rollback)
- Logs the compensation action for observability
- The task remains QUEUED in DB and will be re-claimed by another worker
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueAdapter
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.worker_lease_repository import WorkerLeaseRepository
from backend.runtime.transitions import transition_lease, transition_task

logger = logging.getLogger("ajenda.worker_runtime_service")


class WorkerRuntimeService:
    def __init__(self, session: Session, queue: QueueAdapter) -> None:
        self._session = session
        self._queue = queue
        self._tasks = ExecutionTaskRepository(session)
        self._leases = WorkerLeaseRepository(session)
        self._audit = AuditEventRepository(session)

    def claim_next_task(self, *, tenant_id: str, worker_id: str) -> ExecutionTask | None:
        """Claim the next available task with atomic compensation on DB failure.

        Sequence:
        1. Claim from queue (Redis LMOVE or equivalent)
        2. Validate task exists in DB
        3. Assert no duplicate active lease
        4. Transition task to CLAIMED in DB
        5. Create WorkerLease in DB
        6. Flush DB

        On step 4-6 failure: release the queue claim so the task remains
        available for another worker. Log the compensation.
        """
        message = self._queue.claim_task(tenant_id=tenant_id, worker_id=worker_id)
        if message is None:
            return None

        task = self._tasks.get(message.task_id)
        if task is None or task.tenant_id != tenant_id:
            # Task missing from DB — release the queue claim and skip
            logger.error(
                "claim_task_not_in_db",
                extra={"task_id": str(message.task_id), "worker_id": worker_id},
            )
            self._queue.release_lease(
                tenant_id=tenant_id,
                task_id=message.task_id,
                worker_id=worker_id,
            )
            return None

        try:
            self._assert_no_active_lease(tenant_id=tenant_id, task_id=task.id)
            transition_task(task, ExecutionTaskState.CLAIMED)
            lease = self._leases.add(
                WorkerLease(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    status=WorkerLeaseState.CLAIMED.value,
                    holder_identity=worker_id,
                    heartbeat_at=datetime.now(timezone.utc),
                )
            )
            task.metadata_json = {**task.metadata_json, "worker_lease_id": str(lease.id)}
            self._session.flush()

        except Exception as exc:
            # Compensation: release the queue claim so the task can be re-claimed
            logger.error(
                "claim_db_failed_releasing_queue_claim",
                extra={"task_id": str(task.id), "worker_id": worker_id, "error": str(exc)},
            )
            try:
                self._queue.release_lease(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    worker_id=worker_id,
                )
            except Exception as release_exc:
                logger.critical(
                    "claim_compensation_failed",
                    extra={
                        "task_id": str(task.id),
                        "worker_id": worker_id,
                        "release_error": str(release_exc),
                    },
                )
            raise

        return task

    def heartbeat(
        self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str
    ) -> WorkerLease:
        lease = self._get_owned_lease(
            tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id
        )
        if lease.status not in {
            WorkerLeaseState.CLAIMED.value,
            WorkerLeaseState.ACTIVE.value,
        }:
            raise ValueError("lease is not heartbeat-eligible")

        result = self._queue.heartbeat(
            tenant_id=tenant_id, task_id=lease.task_id, worker_id=worker_id
        )
        if not result.ok:
            raise ValueError(result.reason or "heartbeat rejected")

        if lease.status == WorkerLeaseState.CLAIMED.value:
            transition_lease(lease, WorkerLeaseState.ACTIVE)
        lease.heartbeat_at = datetime.now(timezone.utc)
        self._session.flush()
        return lease

    def start_execution(
        self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str
    ) -> ExecutionTask:
        lease = self._get_owned_lease(
            tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id
        )
        task = self._get_task_for_lease(lease)
        if task.status == ExecutionTaskState.CLAIMED.value:
            transition_task(task, ExecutionTaskState.RUNNING)
            self._session.flush()
        return task

    def complete(
        self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str
    ) -> ExecutionTask:
        lease = self._get_owned_lease(
            tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id
        )
        task = self._get_task_for_lease(lease)
        if task.status != ExecutionTaskState.RUNNING.value:
            raise ValueError("task is not running")

        transition_task(task, ExecutionTaskState.COMPLETED)
        if lease.status != WorkerLeaseState.RELEASED.value:
            transition_lease(lease, WorkerLeaseState.RELEASED)

        result = self._queue.complete_task(
            tenant_id=tenant_id, task_id=task.id, worker_id=worker_id
        )
        if not result.ok:
            raise ValueError(result.reason or "complete rejected")

        lease.heartbeat_at = datetime.now(timezone.utc)
        self._session.flush()

        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="worker",
                action="task_completed",
                actor=worker_id,
                details=f"Completed task {task.id}",
                payload_json={"task_id": str(task.id), "lease_id": str(lease.id)},
            )
        )
        return task

    def fail(
        self,
        *,
        tenant_id: str,
        lease_id: uuid.UUID,
        worker_id: str,
        reason: str,
    ) -> ExecutionTask:
        lease = self._get_owned_lease(
            tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id
        )
        task = self._get_task_for_lease(lease)
        if task.status not in {
            ExecutionTaskState.CLAIMED.value,
            ExecutionTaskState.RUNNING.value,
            ExecutionTaskState.BLOCKED.value,
        }:
            raise ValueError("task is not fail-eligible")

        transition_task(task, ExecutionTaskState.FAILED)
        if lease.status != WorkerLeaseState.RELEASED.value:
            transition_lease(lease, WorkerLeaseState.RELEASED)

        result = self._queue.fail_task(
            tenant_id=tenant_id,
            task_id=task.id,
            worker_id=worker_id,
            reason=reason,
        )
        if not result.ok:
            raise ValueError(result.reason or "fail rejected")

        lease.heartbeat_at = datetime.now(timezone.utc)
        self._session.flush()

        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="worker",
                action="task_failed",
                actor=worker_id,
                details=reason,
                payload_json={"task_id": str(task.id), "lease_id": str(lease.id)},
            )
        )
        return task

    def release(
        self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str
    ) -> WorkerLease:
        lease = self._get_owned_lease(
            tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id
        )
        if lease.status != WorkerLeaseState.RELEASED.value:
            transition_lease(lease, WorkerLeaseState.RELEASED)

        result = self._queue.release_lease(
            tenant_id=tenant_id,
            task_id=lease.task_id,
            worker_id=worker_id,
        )
        if not result.ok:
            raise ValueError(result.reason or "release rejected")

        lease.heartbeat_at = datetime.now(timezone.utc)
        self._session.flush()
        return lease

    def _get_owned_lease(
        self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str
    ) -> WorkerLease:
        lease = self._leases.get(lease_id)
        if (
            lease is None
            or lease.tenant_id != tenant_id
            or lease.holder_identity != worker_id
        ):
            raise ValueError("lease not found for tenant worker")
        return lease

    def _get_task_for_lease(self, lease: WorkerLease) -> ExecutionTask:
        task = self._tasks.get(lease.task_id)
        if task is None:
            raise ValueError("task not found")
        return task

    def _assert_no_active_lease(
        self, *, tenant_id: str, task_id: uuid.UUID
    ) -> None:
        stmt = select(WorkerLease).where(
            WorkerLease.tenant_id == tenant_id,
            WorkerLease.task_id == task_id,
            WorkerLease.status.in_(
                [WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value]
            ),
        )
        existing = self._session.scalars(stmt).first()
        if existing is not None:
            raise ValueError("task already has an active lease")
