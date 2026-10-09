from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.runtime.transitions import transition_lease

if TYPE_CHECKING:
    from backend.services.worker_runtime_service import WorkerRuntimeService

logger = logging.getLogger("ajenda.worker_runtime_queue_reconciliation")


def reconcile_claimed_terminal_queue_artifact(
    service: WorkerRuntimeService,
    *,
    tenant_id: str,
    task: ExecutionTask,
    worker_id: str,
) -> None:
    try:
        result = service._queue.complete_task(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
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
        service._audit.append(
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
        service._session.flush()
        service._session.commit()
    except Exception as exc:
        service._session.rollback()
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


def record_terminal_queue_cleanup_failure(
    service: WorkerRuntimeService,
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
        service._audit.append(
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
        service._session.flush()
        service._session.commit()
    except Exception as exc:
        service._session.rollback()
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


def assert_current_releasable_claim(
    service: WorkerRuntimeService,
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


def assert_no_active_lease(service: WorkerRuntimeService, *, tenant_id: str, task_id: uuid.UUID) -> None:
    stmt = select(WorkerLease).where(
        WorkerLease.tenant_id == tenant_id,
        WorkerLease.task_id == task_id,
        WorkerLease.status.in_([WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value]),
    )
    existing = service._session.scalars(stmt).first()
    if existing is not None:
        raise ValueError("task already has an active lease")


def transition_lease_to_released(service: WorkerRuntimeService, lease: WorkerLease) -> None:
    if lease.status == WorkerLeaseState.RELEASED.value:
        return
    if lease.status == WorkerLeaseState.CLAIMED.value:
        transition_lease(lease, WorkerLeaseState.ACTIVE)
    transition_lease(lease, WorkerLeaseState.RELEASED)


# --- Outcome Review Bridge helpers (for high-risk GTM pilot coherence) ---
