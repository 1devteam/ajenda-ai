"""Worker start admission bridge helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import MISSION_WORKER_START_ADMISSION_SCHEMA_VERSION
from backend.domain.worker_lease import WorkerLease
from backend.services.mission_bridge.read_models import (
    WorkerStartAdmissionRead,
    WorkerStartAdmissionStatus,
    WorkerStartAuthority,
    WorkerStartReceipt,
)


def worker_start_admission_authority_flags(*, read_only: bool = False) -> WorkerStartAuthority:
    return WorkerStartAuthority(
        creates_worker_leases=False,
        claims_tasks=False,
        starts_execution=not read_only,
        dispatches_workers=False,
        executes_handlers=False,
        enqueues_work=False,
        mutates_runtime_state=not read_only,
        read_only=read_only,
    )


def start_admission_blocker(
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


def worker_start_receipt(
    *,
    task: ExecutionTask,
    previous_state: str,
    current_state: str,
    lease: WorkerLease | None,
    task_type: str | None,
    started_at: str,
    idempotency_status: Literal["newly_started", "already_started_by_current_admission", "blocked"],
) -> dict[str, Any]:
    return {
        "task_id": str(task.id),
        "tenant_id": task.tenant_id,
        "mission_id": str(task.mission_id),
        "previous_task_state": previous_state,
        "current_task_state": current_state,
        "worker_lease_id": str(lease.id) if lease is not None else None,
        "lease_scope": {"tenant_id": task.tenant_id, "mission_id": str(task.mission_id), "task_id": str(task.id)},
        "start_source": "worker_start_admission",
        "task_type": task_type,
        "started_at": started_at,
        "idempotency_status": idempotency_status,
    }


def start_admission_status(
    *, newly_started: list[str], already_started: list[str], blocked: list[str], blockers: list[dict[str, Any]]
) -> WorkerStartAdmissionStatus:
    admitted_count = len(newly_started) + len(already_started)
    if admitted_count and (blocked or blockers):
        return "partially_admitted"
    if admitted_count:
        return "admitted"
    return "blocked"


def worker_start_admission_to_read(
    *, mission_id: UUID, tenant_id: str, admission: dict[str, Any], read_only: bool = False
) -> WorkerStartAdmissionRead:
    status = admission.get("admission_status", "blocked")
    if status not in {"admitted", "partially_admitted", "blocked"}:
        status = "blocked"
    raw_authority = admission.get("runtime_authority")
    authority: dict[str, Any] = dict(raw_authority) if isinstance(raw_authority, dict) else {}
    if read_only:
        authority = {
            **authority,
            "creates_worker_leases": False,
            "claims_tasks": False,
            "starts_execution": False,
            "dispatches_workers": False,
            "executes_handlers": False,
            "enqueues_work": False,
            "mutates_runtime_state": False,
            "read_only": True,
        }
    return WorkerStartAdmissionRead(
        mission_id=mission_id,
        tenant_id=tenant_id,
        start_admission_status=status,
        started_task_ids=list(admission.get("started_task_ids") or []),
        already_started_task_ids=list(admission.get("already_started_task_ids") or []),
        skipped_task_ids=list(admission.get("skipped_task_ids") or []),
        blocked_task_ids=list(admission.get("blocked_task_ids") or []),
        start_receipts=[WorkerStartReceipt(**receipt) for receipt in admission.get("start_receipts") or []],
        blockers=list(admission.get("blockers") or []),
        warnings=list(admission.get("warnings") or []),
        worker_start_authority=WorkerStartAuthority(**authority),
        worker_start_admission=admission,
        updated_at=str(admission.get("updated_at") or datetime.now(UTC).isoformat()),
    )


def missing_worker_start_admission(*, mission_id: UUID, tenant_id: str) -> WorkerStartAdmissionRead:
    now = datetime.now(UTC).isoformat()
    admission = {
        "schema_version": MISSION_WORKER_START_ADMISSION_SCHEMA_VERSION,
        "mission_id": str(mission_id),
        "tenant_id": tenant_id,
        "admission_status": "blocked",
        "admission_version": None,
        "started_task_ids": [],
        "already_started_task_ids": [],
        "skipped_task_ids": [],
        "blocked_task_ids": [],
        "start_receipts": [],
        "blockers": [
            start_admission_blocker(
                task_id=None,
                code="worker_start_admission_missing",
                message="Mission has no worker execution start admission metadata.",
            )
        ],
        "warnings": [],
        "runtime_authority": worker_start_admission_authority_flags(read_only=True).model_dump(),
        "updated_at": now,
    }
    return worker_start_admission_to_read(
        mission_id=mission_id, tenant_id=tenant_id, admission=admission, read_only=True
    )


def receipt_worker_lease_id(receipt: dict[str, Any]) -> str:
    raw = receipt.get("worker_lease_id")
    return str(raw) if raw else ""
