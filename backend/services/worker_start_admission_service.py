from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.mission import (
    MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
    MISSION_WORKER_CLAIM_ADMISSION_METADATA_KEY,
    MISSION_WORKER_START_ADMISSION_METADATA_KEY,
    MISSION_WORKER_START_ADMISSION_SCHEMA_VERSION,
)
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.worker_lease_repository import WorkerLeaseRepository
from backend.runtime.transitions import transition_lease, transition_task


class WorkerStartAdmissionService:
    """Owns WorkerStartAdmissionService runtime bridge business logic."""

    def __init__(
        self,
        db: Session,
        *,
        mission_repository_cls: Any = MissionRepository,
        execution_task_repository_cls: Any = ExecutionTaskRepository,
        worker_lease_repository_cls: Any = WorkerLeaseRepository,
    ) -> None:
        self._db = db
        self._mission_repository_cls = mission_repository_cls
        self._execution_task_repository_cls = execution_task_repository_cls
        self._worker_lease_repository_cls = worker_lease_repository_cls

    def admit(self, *, mission_id: UUID, tenant_id: UUID, admitted_by: str) -> Any:
        from backend.api.routes import mission as mission_route

        tenant_id_str = str(tenant_id)
        mission_repo = self._mission_repository_cls(self._db)
        mission = mission_repo.lock_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
        if mission is None:
            raise HTTPException(status_code=404, detail="mission not found for tenant")

        metadata = dict(mission.metadata_json or {})
        claim_admission = metadata.get(MISSION_WORKER_CLAIM_ADMISSION_METADATA_KEY)
        existing_start = metadata.get(MISSION_WORKER_START_ADMISSION_METADATA_KEY)
        if not isinstance(existing_start, dict):
            existing_start = {}
        existing_start_receipts = {
            str(receipt.get("task_id")): receipt
            for receipt in existing_start.get("start_receipts") or []
            if isinstance(receipt, dict) and receipt.get("task_id") is not None
        }
        receipt_started_ids = {
            task_id
            for task_id, receipt in existing_start_receipts.items()
            if receipt.get("idempotency_status") in {"newly_started", "already_started_by_current_admission"}
        }
        existing_started_ids = (
            {str(task_id) for task_id in existing_start.get("started_task_ids") or []}
            | {str(task_id) for task_id in existing_start.get("already_started_task_ids") or []}
            | receipt_started_ids
        )
        now = datetime.now(UTC).isoformat()
        admitted_by = admitted_by

        task_repo = self._execution_task_repository_cls(self._db)
        lease_repo = self._worker_lease_repository_cls(self._db)
        tasks_by_id = {str(task.id): task for task in task_repo.list_for_mission(mission_id=mission_id)}

        started_task_ids: list[str] = []
        already_started_task_ids: list[str] = []
        skipped_task_ids: list[str] = []
        blocked_task_ids: list[str] = []
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []

        if not isinstance(claim_admission, dict):
            blockers.append(
                mission_route._start_admission_blocker(
                    task_id=None,
                    code="worker_claim_admission_missing",
                    message="Worker execution start admission requires current worker claim admission metadata.",
                )
            )
            claimed_task_ids: list[str] = []
            claim_receipts: dict[str, dict[str, Any]] = {}
        else:
            claim_status = claim_admission.get("admission_status")
            if claim_status not in {"admitted", "partially_admitted"}:
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=None,
                        code="worker_claim_admission_not_admitted",
                        message="Worker execution start admission requires admitted or partially admitted worker claims.",
                        details={"claim_admission_status": str(claim_status)},
                    )
                )
                claimed_task_ids = []
                claim_receipts = {}
            else:
                claimed_task_ids = [str(task_id) for task_id in claim_admission.get("claimed_task_ids") or []]
                claim_receipts = {
                    str(receipt.get("task_id")): receipt
                    for receipt in claim_admission.get("claim_receipts") or []
                    if isinstance(receipt, dict) and receipt.get("task_id") is not None
                }
                if not claimed_task_ids:
                    blockers.append(
                        mission_route._start_admission_blocker(
                            task_id=None,
                            code="worker_claim_admission_empty",
                            message="Worker claim admission has no durable claimed_task_ids to start.",
                        )
                    )

        for task_id in sorted(dict.fromkeys(claimed_task_ids)):
            task = tasks_by_id.get(task_id)
            receipt = claim_receipts.get(task_id)
            if receipt is None:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=task_id,
                        code="worker_claim_receipt_missing",
                        message="Claim-admitted task is missing a durable claim receipt.",
                    )
                )
                continue
            if task is None:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=task_id,
                        code="start_task_unavailable",
                        message="Claim-admitted task is unavailable at start admission time.",
                    )
                )
                continue
            if task.tenant_id != tenant_id_str or task.mission_id != mission_id:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=task.id,
                        code="start_task_scope_mismatch",
                        message="Start candidate is not owned by this tenant and mission.",
                        state=task.status,
                    )
                )
                continue
            task_type = mission_route._task_type_for_claim(task)
            if not task_type:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=task.id,
                        code="start_task_missing_task_type",
                        message="Start admission requires explicit non-empty task_type metadata.",
                        state=task.status,
                    )
                )
                continue

            task_metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
            expected_lease_id = str(
                task_metadata.get("worker_lease_id") or mission_route._receipt_worker_lease_id(receipt)
            )
            if not expected_lease_id:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=task.id,
                        code="worker_lease_id_missing",
                        message="Start admission requires a worker_lease_id in task metadata or claim receipt.",
                        state=task.status,
                    )
                )
                continue
            try:
                lease_uuid = UUID(expected_lease_id)
            except ValueError:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=task.id,
                        code="worker_lease_id_invalid",
                        message="Start admission requires a valid worker_lease_id.",
                        state=task.status,
                        details={"worker_lease_id": expected_lease_id},
                    )
                )
                continue

            lease = lease_repo.get(lease_uuid)
            holder_identity = f"worker_claim_admission:{tenant_id_str}:{mission_id}"

            existing_receipt = existing_start_receipts.get(task_id)

            if (
                isinstance(existing_receipt, dict)
                and existing_receipt.get("idempotency_status")
                in {"newly_started", "already_started_by_current_admission"}
                and task.status in {ExecutionTaskState.COMPLETED.value, ExecutionTaskState.FAILED.value}
            ):
                already_started_task_ids.append(task_id)
                receipts.append(
                    mission_route._worker_start_receipt(
                        task=task,
                        previous_state=ExecutionTaskState.CLAIMED.value,
                        current_state=task.status,
                        lease=lease,
                        task_type=task_type,
                        started_at=str(existing_receipt.get("started_at") or now),
                        idempotency_status="already_started_by_current_admission",
                    )
                )
                continue
            if lease is None:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=task.id,
                        code="worker_lease_missing",
                        message="Start admission requires an existing WorkerLease.",
                        state=task.status,
                        details={"worker_lease_id": expected_lease_id},
                    )
                )
                continue
            if lease.tenant_id != tenant_id_str or lease.task_id != task.id:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=task.id,
                        code="worker_lease_scope_mismatch",
                        message="WorkerLease must belong to the same tenant and task as the start candidate.",
                        state=task.status,
                        details={"worker_lease_id": str(lease.id)},
                    )
                )
                continue
            if lease.holder_identity != holder_identity:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=task.id,
                        code="worker_lease_holder_mismatch",
                        message="WorkerLease holder does not match current worker claim admission owner.",
                        state=task.status,
                        details={"worker_lease_id": str(lease.id), "holder_identity": lease.holder_identity},
                    )
                )
                continue
            if lease.status not in {WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value}:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=task.id,
                        code="worker_lease_inactive",
                        message="WorkerLease is not claimed or active.",
                        state=task.status,
                        details={"worker_lease_id": str(lease.id), "lease_status": lease.status},
                    )
                )
                continue

            existing_receipt = existing_start_receipts.get(task_id)
            if task.status == ExecutionTaskState.RUNNING.value:
                if (
                    isinstance(existing_receipt, dict)
                    and existing_receipt.get("worker_lease_id") == str(lease.id)
                    and existing_receipt.get("idempotency_status")
                    in {"newly_started", "already_started_by_current_admission"}
                ):
                    already_started_task_ids.append(task_id)
                    receipts.append(
                        mission_route._worker_start_receipt(
                            task=task,
                            previous_state=ExecutionTaskState.CLAIMED.value,
                            current_state=ExecutionTaskState.RUNNING.value,
                            lease=lease,
                            task_type=task_type,
                            started_at=str(existing_receipt.get("started_at") or now),
                            idempotency_status="already_started_by_current_admission",
                        )
                    )
                else:
                    blocked_task_ids.append(task_id)
                    blockers.append(
                        mission_route._start_admission_blocker(
                            task_id=task.id,
                            code="task_running_without_current_start_admission",
                            message="Task is already running without a matching current start admission receipt.",
                            state=task.status,
                            details={"worker_lease_id": str(lease.id)},
                        )
                    )
                continue
            if task.status != ExecutionTaskState.CLAIMED.value:
                blocked_task_ids.append(task_id)
                skipped_task_ids.append(task_id)
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=task.id,
                        code="start_task_not_claimed",
                        message="Worker execution start admission only starts claimed tasks.",
                        state=task.status,
                    )
                )
                continue

            previous_task_status = task.status
            previous_lease_status = lease.status
            previous_heartbeat_at = lease.heartbeat_at
            savepoint = self._db.begin_nested()
            try:
                if lease.status == WorkerLeaseState.CLAIMED.value:
                    transition_lease(lease, WorkerLeaseState.ACTIVE)
                lease.heartbeat_at = datetime.now(UTC)
                transition_task(task, ExecutionTaskState.RUNNING)
                self._db.add(lease)
                self._db.add(task)
                self._db.flush()
                savepoint.commit()
            except Exception as exc:
                if getattr(savepoint, "is_active", False):
                    savepoint.rollback()
                task.status = previous_task_status
                lease.status = previous_lease_status
                lease.heartbeat_at = previous_heartbeat_at
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._start_admission_blocker(
                        task_id=task.id,
                        code="start_transition_failed",
                        message="Canonical claimed-to-running transition failed.",
                        state=getattr(task, "status", None),
                        details={"reason": str(exc)},
                    )
                )
                continue
            started_task_ids.append(task_id)
            receipts.append(
                mission_route._worker_start_receipt(
                    task=task,
                    previous_state=ExecutionTaskState.CLAIMED.value,
                    current_state=ExecutionTaskState.RUNNING.value,
                    lease=lease,
                    task_type=task_type,
                    started_at=now,
                    idempotency_status="newly_started",
                )
            )

        status = mission_route._start_admission_status(
            newly_started=started_task_ids,
            already_started=already_started_task_ids,
            blocked=list(dict.fromkeys(blocked_task_ids)),
            blockers=blockers,
        )
        previous_version = existing_start.get("admission_version") if isinstance(existing_start, dict) else None
        admission_version = int(previous_version or 0) + 1
        admission = {
            "schema_version": MISSION_WORKER_START_ADMISSION_SCHEMA_VERSION,
            "mission_id": str(mission_id),
            "tenant_id": tenant_id_str,
            "admission_status": status,
            "admission_version": admission_version,
            "started_task_ids": sorted(set(started_task_ids) | set(already_started_task_ids) | existing_started_ids),
            "already_started_task_ids": already_started_task_ids,
            "skipped_task_ids": list(dict.fromkeys(skipped_task_ids)),
            "blocked_task_ids": list(dict.fromkeys(blocked_task_ids)),
            "start_receipts": receipts,
            "blockers": blockers,
            "warnings": warnings,
            "materialization_reference": claim_admission.get("materialization_reference")
            if isinstance(claim_admission, dict)
            else metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY),
            "queue_admission_reference": claim_admission.get("queue_admission_reference")
            if isinstance(claim_admission, dict)
            else metadata.get(MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY),
            "dispatch_readiness_summary": claim_admission.get("dispatch_readiness_summary")
            if isinstance(claim_admission, dict)
            else {},
            "worker_dispatch_eligibility_summary": claim_admission.get("worker_dispatch_eligibility_summary")
            if isinstance(claim_admission, dict)
            else {},
            "worker_claim_preview_reference": claim_admission.get("worker_claim_preview_reference")
            if isinstance(claim_admission, dict)
            else {},
            "worker_claim_admission_reference": {
                "admission_status": claim_admission.get("admission_status"),
                "admission_version": claim_admission.get("admission_version"),
                "claimed_task_ids": claim_admission.get("claimed_task_ids") or [],
                "claim_receipt_count": len(claim_admission.get("claim_receipts") or []),
                "updated_at": claim_admission.get("updated_at"),
            }
            if isinstance(claim_admission, dict)
            else {},
            "start_admitted_by": admitted_by,
            "start_admitted_at": now,
            "updated_at": now,
            "runtime_authority": mission_route._worker_start_admission_authority_flags(read_only=False).model_dump(),
        }
        metadata[MISSION_WORKER_START_ADMISSION_METADATA_KEY] = admission
        mission_repo.update_metadata(mission=mission, metadata_json=metadata)
        return mission_route._worker_start_admission_to_read(
            mission_id=mission_id, tenant_id=tenant_id_str, admission=admission
        )
