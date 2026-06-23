"""Worker run admission bridge helpers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import MISSION_WORKER_RUN_ADMISSION_SCHEMA_VERSION
from backend.domain.worker_lease import WorkerLease
from backend.services.mission_bridge.read_models import (
    WorkerRunAdmissionRead,
    WorkerRunAdmissionStatus,
    WorkerRunAuthority,
    WorkerRunReceipt,
)


def worker_run_admission_authority_flags(
    *, read_only: bool = False, completed: bool = False, failed: bool = False
) -> WorkerRunAuthority:
    return WorkerRunAuthority(
        creates_worker_leases=False,
        claims_tasks=False,
        starts_execution=False,
        dispatches_workers=not read_only,
        executes_handlers=not read_only,
        executes_adapters=False,
        enqueues_work=False,
        requires_queue_claim=True,
        completes_tasks=completed and not read_only,
        fails_tasks=failed and not read_only,
        mutates_runtime_state=not read_only,
        read_only=read_only,
    )


def run_admission_blocker(
    *,
    task_id: UUID | str | None,
    code: str,
    message: str,
    state: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {"task_id": str(task_id) if task_id is not None else None, "code": code, "message": message}
    if state is not None:
        item["state"] = state
    if details:
        item["details"] = details
    return item


def safe_run_summary(task: ExecutionTask, *, handler_key: str) -> dict[str, Any]:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    return {
        "handler_key": handler_key,
        "metadata_keys": sorted(str(key) for key in metadata.keys()),
        "task_type": metadata.get("task_type") if isinstance(metadata.get("task_type"), str) else None,
    }


def tenant_aware_dispatcher_session_factory(*, request: Request, tenant_id: str) -> Callable[[], Session]:
    runtime = request.app.state.database_runtime

    def _factory() -> Session:
        session = cast(Session, runtime.session_factory())
        session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
        session_any = cast(Any, session)
        session_any._ajenda_tenant_id = tenant_id
        session_any._ajenda_rls_context_applied = True
        return session

    _factory.tenant_id = tenant_id  # type: ignore[attr-defined]
    _factory.rls_context_applied = True  # type: ignore[attr-defined]
    return _factory


def run_admission_status(
    *,
    completed: list[str],
    failed: list[str],
    already_completed: list[str],
    already_failed: list[str],
    blocked: list[str],
) -> WorkerRunAdmissionStatus:
    terminal_count = len(completed) + len(failed) + len(already_completed) + len(already_failed)
    if terminal_count and blocked:
        return "partially_completed"
    if completed or already_completed:
        if failed or already_failed:
            return "partially_completed"
        return "completed"
    if failed or already_failed:
        return "failed"
    return "blocked"


def worker_run_admission_to_read(
    *, mission_id: UUID, tenant_id: str, admission: dict[str, Any], read_only: bool = False
) -> WorkerRunAdmissionRead:
    status = admission.get("admission_status", "blocked")
    if status not in {"completed", "partially_completed", "failed", "blocked"}:
        status = "blocked"
    authority = dict(admission.get("runtime_authority") or {})
    if read_only:
        authority = {
            **authority,
            "creates_worker_leases": False,
            "claims_tasks": False,
            "starts_execution": False,
            "dispatches_workers": False,
            "executes_handlers": False,
            "enqueues_work": False,
            "requires_queue_claim": True,
            "completes_tasks": False,
            "fails_tasks": False,
            "mutates_runtime_state": False,
            "read_only": True,
        }
    return WorkerRunAdmissionRead(
        mission_id=mission_id,
        tenant_id=tenant_id,
        run_admission_status=status,
        executed_task_ids=list(admission.get("executed_task_ids") or []),
        completed_task_ids=list(admission.get("completed_task_ids") or []),
        failed_task_ids=list(admission.get("failed_task_ids") or []),
        already_completed_task_ids=list(admission.get("already_completed_task_ids") or []),
        already_failed_task_ids=list(admission.get("already_failed_task_ids") or []),
        skipped_task_ids=list(admission.get("skipped_task_ids") or []),
        blocked_task_ids=list(admission.get("blocked_task_ids") or []),
        run_receipts=[WorkerRunReceipt(**receipt) for receipt in admission.get("run_receipts") or []],
        queue_claim_receipts=list(admission.get("queue_claim_receipts") or []),
        blockers=list(admission.get("blockers") or []),
        warnings=list(admission.get("warnings") or []),
        worker_run_authority=WorkerRunAuthority(**authority),
        worker_run_admission=admission,
        updated_at=str(admission.get("updated_at") or datetime.now(UTC).isoformat()),
    )


def missing_worker_run_admission(*, mission_id: UUID, tenant_id: str) -> WorkerRunAdmissionRead:
    now = datetime.now(UTC).isoformat()
    admission: dict[str, Any] = {
        "schema_version": MISSION_WORKER_RUN_ADMISSION_SCHEMA_VERSION,
        "mission_id": str(mission_id),
        "tenant_id": tenant_id,
        "admission_status": "blocked",
        "admission_version": None,
        "executed_task_ids": [],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "already_completed_task_ids": [],
        "already_failed_task_ids": [],
        "skipped_task_ids": [],
        "blocked_task_ids": [],
        "run_receipts": [],
        "queue_claim_receipts": [],
        "blockers": [
            run_admission_blocker(
                task_id=None,
                code="worker_run_admission_missing",
                message="Mission has no worker run admission metadata.",
            )
        ],
        "warnings": [],
        "runtime_authority": worker_run_admission_authority_flags(read_only=True).model_dump(),
        "updated_at": now,
    }
    return worker_run_admission_to_read(mission_id=mission_id, tenant_id=tenant_id, admission=admission, read_only=True)


def run_attempt_identity(
    *, task_id: UUID | str, worker_lease_id: str | None, started_from_admission_at: str | None, retry_count: int | None
) -> dict[str, Any]:
    return {
        "task_id": str(task_id),
        "worker_lease_id": worker_lease_id,
        "started_from_admission_at": started_from_admission_at,
        "retry_count": retry_count,
    }


def retry_count_for_run_attempt(task: ExecutionTask, start_receipt: dict[str, Any]) -> int | None:
    raw_retry_count = start_receipt.get("retry_count")
    if raw_retry_count is None:
        raw_retry_count = getattr(task, "retry_count", None)
    if raw_retry_count is None:
        task_metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
        raw_retry_count = task_metadata.get("retry_count")
    if raw_retry_count is None:
        return None
    try:
        return int(raw_retry_count)
    except (TypeError, ValueError):
        return None


def run_receipt_matches_attempt(
    *,
    receipt: dict[str, Any],
    task_id: str,
    worker_lease_id: str,
    started_from_admission_at: str | None,
    retry_count: int | None,
) -> bool:
    if str(receipt.get("task_id") or "") != task_id:
        return False
    if str(receipt.get("worker_lease_id") or "") != worker_lease_id:
        return False
    receipt_started_at = receipt.get("started_from_admission_at")
    raw_attempt_identity = receipt.get("attempt_identity")
    attempt_identity: dict[str, Any] = raw_attempt_identity if isinstance(raw_attempt_identity, dict) else {}
    if receipt_started_at is None:
        receipt_started_at = attempt_identity.get("started_from_admission_at")
    if str(receipt_started_at or "") != str(started_from_admission_at or ""):
        return False
    receipt_retry_count = receipt.get("retry_count")
    if receipt_retry_count is None:
        receipt_retry_count = attempt_identity.get("retry_count")
    if receipt_retry_count is None or retry_count is None:
        return True
    try:
        return int(receipt_retry_count) == int(retry_count)
    except (TypeError, ValueError):
        return False


def run_receipt(
    *,
    task: ExecutionTask,
    previous_state: str,
    current_state: str,
    lease: WorkerLease | None,
    queue_claim: dict[str, Any],
    task_type: str,
    started_from_admission_at: str | None,
    retry_count: int | None,
    executed_at: str,
    completed_at: str | None = None,
    failed_at: str | None = None,
    result_summary: dict[str, Any] | None = None,
    error_summary: dict[str, Any] | None = None,
    idempotency_status: Literal[
        "newly_executed",
        "already_completed_by_current_run_admission",
        "already_failed_by_current_run_admission",
        "blocked",
    ] = "newly_executed",
) -> dict[str, Any]:
    return {
        "task_id": str(task.id),
        "tenant_id": task.tenant_id,
        "mission_id": str(task.mission_id),
        "previous_task_state": previous_state,
        "current_task_state": current_state,
        "worker_lease_id": str(lease.id) if lease is not None else None,
        "lease_scope": {"tenant_id": task.tenant_id, "mission_id": str(task.mission_id), "task_id": str(task.id)},
        "queue_claim": queue_claim,
        "run_source": "worker_run_admission",
        "task_type": task_type,
        "handler_name": task_type,
        "handler_key": task_type,
        "started_from_admission_at": started_from_admission_at,
        "retry_count": retry_count,
        "attempt_identity": run_attempt_identity(
            task_id=task.id,
            worker_lease_id=str(lease.id) if lease is not None else None,
            started_from_admission_at=started_from_admission_at,
            retry_count=retry_count,
        ),
        "executed_at": executed_at,
        "completed_at": completed_at,
        "failed_at": failed_at,
        "result_summary": result_summary or {},
        "error_summary": error_summary,
        "idempotency_status": idempotency_status,
    }
