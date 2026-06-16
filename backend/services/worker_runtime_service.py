from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueAdapter
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.lineage_record_repository import LineageRecordRepository
from backend.repositories.worker_lease_repository import WorkerLeaseRepository
from backend.runtime.transitions import transition_lease, transition_task
from backend.services.tools.evidence_bridge import build_tool_action_evidence_records

logger = logging.getLogger("ajenda.worker_runtime_service")

_TERMINAL_TASK_STATES: frozenset[str] = frozenset(
    {
        ExecutionTaskState.COMPLETED.value,
        ExecutionTaskState.FAILED.value,
        ExecutionTaskState.CANCELLED.value,
        ExecutionTaskState.DEAD_LETTERED.value,
    }
)


class WorkerRuntimeService:
    def __init__(self, session: Session, queue: QueueAdapter) -> None:
        self._session = session
        self._queue = queue
        self._tasks = ExecutionTaskRepository(session)
        self._leases = WorkerLeaseRepository(session)
        self._audit = AuditEventRepository(session)

    def claim_next_task(self, *, tenant_id: str, worker_id: str) -> ExecutionTask | None:
        message = self._queue.claim_task(tenant_id=tenant_id, worker_id=worker_id)
        if message is None:
            return None

        task = self._tasks.get(message.task_id)
        if task is None or task.tenant_id != tenant_id:
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

        if task.status in _TERMINAL_TASK_STATES:
            self._reconcile_claimed_terminal_queue_artifact(
                tenant_id=tenant_id,
                task=task,
                worker_id=worker_id,
            )
            return None

        savepoint = self._session.begin_nested()
        try:
            self._assert_no_active_lease(tenant_id=tenant_id, task_id=task.id)
            transition_task(task, ExecutionTaskState.CLAIMED)
            lease = self._leases.add(
                WorkerLease(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    status=WorkerLeaseState.CLAIMED.value,
                    holder_identity=worker_id,
                    heartbeat_at=datetime.now(UTC),
                )
            )
            task.metadata_json = {**task.metadata_json, "worker_lease_id": str(lease.id)}
            self._session.flush()
            savepoint.commit()
            self._session.commit()
        except Exception as exc:
            logger.error(
                "claim_db_failed_releasing_queue_claim",
                extra={"task_id": str(task.id), "worker_id": worker_id, "error": str(exc)},
            )
            if savepoint.is_active:
                savepoint.rollback()
            else:
                self._session.rollback()
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

    def heartbeat(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> WorkerLease:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        if lease.status not in {WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value}:
            raise ValueError("lease is not heartbeat-eligible")

        result = self._queue.heartbeat(tenant_id=tenant_id, task_id=lease.task_id, worker_id=worker_id)
        if not result.ok:
            raise ValueError(result.reason or "heartbeat rejected")

        if lease.status == WorkerLeaseState.CLAIMED.value:
            transition_lease(lease, WorkerLeaseState.ACTIVE)
        lease.heartbeat_at = datetime.now(UTC)
        self._session.flush()
        self._session.commit()
        return lease

    def start_execution(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> ExecutionTask:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status == ExecutionTaskState.CLAIMED.value:
            if lease.status == WorkerLeaseState.CLAIMED.value:
                transition_lease(lease, WorkerLeaseState.ACTIVE)
            lease.heartbeat_at = datetime.now(UTC)
            transition_task(task, ExecutionTaskState.RUNNING)
            self._session.flush()
            self._session.commit()
        return task

    def complete(
        self,
        *,
        tenant_id: str,
        lease_id: uuid.UUID,
        worker_id: str,
        task_output: dict[str, Any] | None = None,
        output_reason: str | None = None,
    ) -> ExecutionTask:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status != ExecutionTaskState.RUNNING.value:
            raise ValueError("task is not running")

        transition_task(task, ExecutionTaskState.COMPLETED)
        self._transition_lease_to_released(lease)
        lease.heartbeat_at = datetime.now(UTC)
        if task_output is not None:
            lineage_record = LineageRecordRepository(self._session).append(
                LineageRecord(
                    tenant_id=task.tenant_id,
                    mission_id=task.mission_id,
                    fleet_id=task.fleet_id,
                    branch_id=task.branch_id,
                    task_id=task.id,
                    worker_lease_id=lease.id,
                    relationship_type="task_output",
                    relationship_reason=output_reason,
                    metadata_json=task_output,
                )
            )
            evidence_repo = EvidenceRepository(self._session)
            for evidence_record in build_tool_action_evidence_records(
                task=task,
                lease=lease,
                task_output=task_output,
                lineage_record=lineage_record,
            ):
                evidence_repo.add(evidence_record)

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
        self._session.flush()
        self._session.commit()

        self._cleanup_terminal_queue_claim_after_commit(
            tenant_id=tenant_id,
            task=task,
            lease=lease,
            worker_id=worker_id,
            queue_operation="complete_task",
            audit_action="terminal_queue_complete_cleanup_failed",
            rejected_reason="complete rejected",
        )
        return task

    def block_completion_failure(
        self,
        *,
        tenant_id: str,
        lease_id: uuid.UUID,
        worker_id: str,
        task_type: str,
        side_effect_class: str,
        reason: str,
    ) -> ExecutionTask:
        """Block a task after a side-effecting handler completed but completion persistence failed."""

        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status != ExecutionTaskState.RUNNING.value:
            raise ValueError("task is not running")

        transition_task(task, ExecutionTaskState.BLOCKED)
        self._transition_lease_to_released(lease)
        lease.heartbeat_at = datetime.now(UTC)
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="worker",
                action="task_completion_failed_after_side_effect",
                actor=worker_id,
                details=(f"Blocked task {task.id} after completed {task_type} side effect failed completion: {reason}"),
                payload_json={
                    "task_id": str(task.id),
                    "lease_id": str(lease.id),
                    "task_type": task_type,
                    "side_effect_class": side_effect_class,
                    "reason": reason,
                    "handler_completed": True,
                    "requeue_allowed": False,
                },
            )
        )
        self._session.flush()
        self._session.commit()

        self._cleanup_terminal_queue_claim_after_commit(
            tenant_id=tenant_id,
            task=task,
            lease=lease,
            worker_id=worker_id,
            queue_operation="complete_task",
            audit_action="completion_failure_queue_complete_cleanup_failed",
            rejected_reason="complete rejected",
        )
        return task

    def block_completion_failure(
        self,
        *,
        tenant_id: str,
        lease_id: uuid.UUID,
        worker_id: str,
        task_type: str,
        side_effect_class: str,
        reason: str,
    ) -> ExecutionTask:
        """Block a task after a side-effecting handler completed but completion persistence failed."""

        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status != ExecutionTaskState.RUNNING.value:
            raise ValueError("task is not running")

        transition_task(task, ExecutionTaskState.BLOCKED)
        self._transition_lease_to_released(lease)
        lease.heartbeat_at = datetime.now(UTC)
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="worker",
                action="task_completion_failed_after_side_effect",
                actor=worker_id,
                details=(f"Blocked task {task.id} after completed {task_type} side effect failed completion: {reason}"),
                payload_json={
                    "task_id": str(task.id),
                    "lease_id": str(lease.id),
                    "task_type": task_type,
                    "side_effect_class": side_effect_class,
                    "reason": reason,
                    "handler_completed": True,
                    "requeue_allowed": False,
                },
            )
        )
        self._session.flush()
        self._session.commit()

        result = self._queue.complete_task(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
        if not result.ok:
            self._record_terminal_queue_cleanup_failure(
                tenant_id=tenant_id,
                task=task,
                lease=lease,
                worker_id=worker_id,
                queue_operation="complete_task",
                audit_action="completion_failure_queue_complete_cleanup_failed",
                reason=result.reason or "complete rejected",
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
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status not in {
            ExecutionTaskState.CLAIMED.value,
            ExecutionTaskState.RUNNING.value,
            ExecutionTaskState.BLOCKED.value,
        }:
            raise ValueError("task is not fail-eligible")

        transition_task(task, ExecutionTaskState.FAILED)
        self._transition_lease_to_released(lease)
        lease.heartbeat_at = datetime.now(UTC)
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
        self._session.flush()
        self._session.commit()

        self._cleanup_terminal_queue_claim_after_commit(
            tenant_id=tenant_id,
            task=task,
            lease=lease,
            worker_id=worker_id,
            queue_operation="fail_task",
            audit_action="terminal_queue_fail_cleanup_failed",
            rejected_reason="fail rejected",
            fail_reason=reason,
        )
        return task

    def release(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> WorkerLease:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        self._assert_current_releasable_claim(tenant_id=tenant_id, lease=lease, task=task)

        self._transition_lease_to_released(lease)
        transition_task(task, ExecutionTaskState.QUEUED)
        result = self._queue.release_lease(
            tenant_id=tenant_id,
            task_id=lease.task_id,
            worker_id=worker_id,
        )
        if not result.ok:
            self._session.rollback()
            raise ValueError(result.reason or "release rejected")
        lease.heartbeat_at = datetime.now(UTC)
        self._session.flush()
        self._session.commit()
        return lease

    def _cleanup_terminal_queue_claim_after_commit(
        self,
        *,
        tenant_id: str,
        task: ExecutionTask,
        lease: WorkerLease,
        worker_id: str,
        queue_operation: str,
        audit_action: str,
        rejected_reason: str,
        fail_reason: str | None = None,
    ) -> None:
        try:
            if queue_operation == "complete_task":
                result = self._queue.complete_task(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
            elif queue_operation == "fail_task":
                result = self._queue.fail_task(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    worker_id=worker_id,
                    reason=fail_reason or rejected_reason,
                )
            else:
                raise ValueError(f"unsupported terminal queue operation: {queue_operation}")
        except Exception as exc:
            self._record_terminal_queue_cleanup_failure(
                tenant_id=tenant_id,
                task=task,
                lease=lease,
                worker_id=worker_id,
                queue_operation=queue_operation,
                audit_action=audit_action,
                reason=f"{queue_operation} raised: {exc}",
            )
            return

        if not result.ok:
            self._record_terminal_queue_cleanup_failure(
                tenant_id=tenant_id,
                task=task,
                lease=lease,
                worker_id=worker_id,
                queue_operation=queue_operation,
                audit_action=audit_action,
                reason=result.reason or rejected_reason,
            )

    def _reconcile_claimed_terminal_queue_artifact(
        self,
        *,
        tenant_id: str,
        task: ExecutionTask,
        worker_id: str,
    ) -> None:
        try:
            result = self._queue.complete_task(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
            cleanup_ok = result.ok
            reason = result.reason or "complete rejected"
        except Exception as exc:
            cleanup_ok = False
            reason = f"complete_task raised: {exc}"

        action = "terminal_task_queue_claim_reconciled" if cleanup_ok else "terminal_task_queue_claim_cleanup_failed"
        if cleanup_ok:
            details = f"Removed stale queue claim for terminal task {task.id}."
            logger.info(
                "terminal_task_queue_claim_reconciled",
                extra={
                    "tenant_id": tenant_id,
                    "task_id": str(task.id),
                    "task_status": task.status,
                    "worker_id": worker_id,
                },
            )
        else:
            details = f"Queue cleanup failed for terminal task {task.id}: {reason}"
            logger.critical(
                "terminal_task_queue_claim_cleanup_failed",
                extra={
                    "tenant_id": tenant_id,
                    "task_id": str(task.id),
                    "task_status": task.status,
                    "worker_id": worker_id,
                    "reason": reason,
                },
            )

        try:
            self._audit.append(
                AuditEvent(
                    tenant_id=tenant_id,
                    mission_id=task.mission_id,
                    category="worker_queue_cleanup",
                    action=action,
                    actor=worker_id,
                    details=details,
                    payload_json={
                        "task_id": str(task.id),
                        "task_status": task.status,
                        "queue_operation": "complete_task",
                        "cleanup_succeeded": cleanup_ok,
                        "reason": None if cleanup_ok else reason,
                        "requeue_allowed": False,
                    },
                )
            )
            self._session.flush()
            self._session.commit()
        except Exception as exc:
            self._session.rollback()
            logger.critical(
                "terminal_task_queue_claim_reconciliation_audit_failed",
                extra={
                    "tenant_id": tenant_id,
                    "task_id": str(task.id),
                    "task_status": task.status,
                    "worker_id": worker_id,
                    "cleanup_succeeded": cleanup_ok,
                    "cleanup_reason": reason,
                    "audit_error": str(exc),
                },
            )

    def _record_terminal_queue_cleanup_failure(
        self,
        *,
        tenant_id: str,
        task: ExecutionTask,
        lease: WorkerLease,
        worker_id: str,
        queue_operation: str,
        audit_action: str,
        reason: str,
    ) -> None:
        logger.critical(
            f"queue_{queue_operation}_after_db_commit_failed",
            extra={
                "tenant_id": tenant_id,
                "task_id": str(task.id),
                "task_status": task.status,
                "lease_id": str(lease.id),
                "lease_status": lease.status,
                "worker_id": worker_id,
                "reason": reason,
            },
        )
        try:
            self._audit.append(
                AuditEvent(
                    tenant_id=tenant_id,
                    mission_id=task.mission_id,
                    category="worker_queue_cleanup",
                    action=audit_action,
                    actor=worker_id,
                    details=(
                        f"Queue {queue_operation} cleanup failed after DB terminal commit for task {task.id}: {reason}"
                    ),
                    payload_json={
                        "task_id": str(task.id),
                        "task_status": task.status,
                        "lease_id": str(lease.id),
                        "lease_status": lease.status,
                        "queue_operation": queue_operation,
                        "reason": reason,
                        "requeue_allowed": False,
                    },
                )
            )
            self._session.flush()
            self._session.commit()
        except Exception as exc:
            self._session.rollback()
            logger.critical(
                "terminal_queue_cleanup_failure_audit_persist_failed",
                extra={
                    "tenant_id": tenant_id,
                    "task_id": str(task.id),
                    "lease_id": str(lease.id),
                    "queue_operation": queue_operation,
                    "queue_reason": reason,
                    "audit_error": str(exc),
                },
            )

    def _assert_current_releasable_claim(
        self,
        *,
        tenant_id: str,
        lease: WorkerLease,
        task: ExecutionTask,
    ) -> None:
        if lease.status not in {WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value}:
            raise ValueError("lease is not release-eligible")
        if task.tenant_id != tenant_id or lease.tenant_id != tenant_id:
            raise ValueError("task not found for tenant lease")
        if task.status != ExecutionTaskState.CLAIMED.value:
            raise ValueError("task is not claimed")
        if not isinstance(task.metadata_json, dict) or task.metadata_json.get("worker_lease_id") != str(lease.id):
            raise ValueError("lease is not current task claim")

    def _get_owned_lease(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> WorkerLease:
        lease = self._leases.get(lease_id)
        if lease is None or lease.tenant_id != tenant_id or lease.holder_identity != worker_id:
            raise ValueError("lease not found for tenant worker")
        return lease

    def _get_task_for_lease(self, lease: WorkerLease) -> ExecutionTask:
        task = self._tasks.get(lease.task_id)
        if task is None:
            raise ValueError("task not found")
        return task

    def _assert_no_active_lease(self, *, tenant_id: str, task_id: uuid.UUID) -> None:
        stmt = select(WorkerLease).where(
            WorkerLease.tenant_id == tenant_id,
            WorkerLease.task_id == task_id,
            WorkerLease.status.in_([WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value]),
        )
        existing = self._session.scalars(stmt).first()
        if existing is not None:
            raise ValueError("task already has an active lease")

    def _transition_lease_to_released(self, lease: WorkerLease) -> None:
        if lease.status == WorkerLeaseState.RELEASED.value:
            return
        if lease.status == WorkerLeaseState.CLAIMED.value:
            transition_lease(lease, WorkerLeaseState.ACTIVE)
        transition_lease(lease, WorkerLeaseState.RELEASED)
