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
    MISSION_WORKER_CLAIM_ADMISSION_SCHEMA_VERSION,
)
from backend.domain.worker_lease import WorkerLease
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.worker_lease_repository import WorkerLeaseRepository
from backend.runtime.transitions import transition_task


class WorkerClaimAdmissionService:
    """Owns WorkerClaimAdmissionService runtime bridge business logic."""

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

        preview = mission_route._build_worker_claim_preview(mission_id=mission_id, tenant_id=tenant_id, db=self._db)
        metadata = dict(mission.metadata_json or {})
        existing_admission = metadata.get(MISSION_WORKER_CLAIM_ADMISSION_METADATA_KEY)
        if not isinstance(existing_admission, dict):
            existing_admission = {}
        existing_receipts = {
            str(receipt.get("task_id")): receipt
            for receipt in existing_admission.get("claim_receipts") or []
            if isinstance(receipt, dict) and receipt.get("task_id") is not None
        }
        receipt_claimed_ids = {
            task_id
            for task_id, receipt in existing_receipts.items()
            if receipt.get("idempotency_status") in {"newly_claimed", "already_claimed_by_current_admission"}
        }
        existing_claimed_ids = (
            {str(task_id) for task_id in existing_admission.get("claimed_task_ids") or []}
            | {str(task_id) for task_id in existing_admission.get("already_claimed_task_ids") or []}
            | receipt_claimed_ids
        )

        task_repo = self._execution_task_repository_cls(self._db)
        lease_repo = self._worker_lease_repository_cls(self._db)
        tasks_by_id = {str(task.id): task for task in task_repo.list_for_mission(mission_id=mission_id)}
        preview_ids = {envelope.task_id for envelope in preview.claim_preview_envelopes}
        preview_task_types = {envelope.task_id: envelope.task_type for envelope in preview.claim_preview_envelopes}
        holder_identity = f"worker_claim_admission:{tenant_id_str}:{mission_id}"
        admitted_by = admitted_by
        now = datetime.now(UTC).isoformat()

        claimed_task_ids: list[str] = []
        already_claimed_task_ids: list[str] = []
        skipped_task_ids = list(dict.fromkeys(preview.skipped_task_ids))
        blocked_task_ids = list(dict.fromkeys(preview.blocked_task_ids))
        blockers = [dict(item) for item in preview.blockers]
        warnings = [dict(item) for item in preview.warnings]
        receipts: list[dict[str, Any]] = []
        created_lease_count = 0

        for task_id in list(blocked_task_ids):
            task = tasks_by_id.get(task_id)
            if task is None:
                continue
            active_leases = mission_route._active_worker_leases_for_task(lease_repo, task.id)
            foreign_active_lease = next(
                (lease for lease in active_leases if lease.holder_identity != holder_identity), None
            )
            if foreign_active_lease is not None:
                blockers.append(
                    mission_route._claim_admission_blocker(
                        task_id=task.id,
                        code="task_claimed_by_different_active_lease",
                        message="Task already has an active worker lease owned by a different holder.",
                        state=task.status,
                        details={"worker_lease_id": str(foreign_active_lease.id)},
                    )
                )

        for task_id in sorted(preview_ids):
            task = tasks_by_id.get(task_id)
            if task is None:
                if task_id not in blocked_task_ids:
                    blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._claim_admission_blocker(
                        task_id=task_id,
                        code="claim_preview_task_unavailable",
                        message="Worker claim preview task is unavailable at claim admission time.",
                    )
                )
                continue
            if task.tenant_id != tenant_id_str or task.mission_id != mission_id:
                if task_id not in blocked_task_ids:
                    blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._claim_admission_blocker(
                        task_id=task.id,
                        code="claim_task_scope_mismatch",
                        message="Preview task is not owned by this tenant and mission at claim admission time.",
                        state=task.status,
                    )
                )
                continue
            task_type = mission_route._task_type_for_claim(task)
            if not task_type:
                if task_id not in blocked_task_ids:
                    blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._claim_admission_blocker(
                        task_id=task.id,
                        code="claim_task_missing_task_type",
                        message="Claim admission requires explicit non-empty task_type metadata.",
                        state=task.status,
                    )
                )
                continue
            active_leases = mission_route._active_worker_leases_for_task(lease_repo, task.id)
            foreign_active_lease = next(
                (lease for lease in active_leases if lease.holder_identity != holder_identity), None
            )
            if foreign_active_lease is not None:
                if task_id not in blocked_task_ids:
                    blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._claim_admission_blocker(
                        task_id=task.id,
                        code="task_claimed_by_different_active_lease",
                        message="Task already has an active worker lease owned by a different holder.",
                        state=task.status,
                        details={"worker_lease_id": str(foreign_active_lease.id)},
                    )
                )
                continue
            active_leases = mission_route._active_worker_leases_for_task(lease_repo, task.id)
            current_lease = next((lease for lease in active_leases if lease.holder_identity == holder_identity), None)

            if (
                task.status in {ExecutionTaskState.CLAIMED.value, ExecutionTaskState.RUNNING.value}
                and current_lease is not None
            ):
                already_claimed_task_ids.append(task_id)
                continue

            if task.status != ExecutionTaskState.QUEUED.value:
                if task_id not in blocked_task_ids:
                    blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._claim_admission_blocker(
                        task_id=task.id,
                        code="claim_task_not_queued",
                        message="Claim admission only claims tasks that remain queued.",
                        state=task.status,
                    )
                )
                continue
            lease = WorkerLease(
                tenant_id=tenant_id_str,
                task_id=task.id,
                status=WorkerLeaseState.CLAIMED.value,
                holder_identity=holder_identity,
                heartbeat_at=datetime.now(UTC),
                metadata_json={"claim_source": "worker_claim_admission", "mission_id": str(mission_id)},
            )
            previous_metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
            savepoint = self._db.begin_nested()
            try:
                transition_task(task, ExecutionTaskState.CLAIMED)
                lease = lease_repo.add(lease)
                task.metadata_json = {
                    **(task.metadata_json if isinstance(task.metadata_json, dict) else {}),
                    "worker_lease_id": str(lease.id),
                }
                self._db.add(task)
                self._db.flush()
                savepoint.commit()
            except Exception as exc:
                if getattr(savepoint, "is_active", False):
                    savepoint.rollback()
                if getattr(task, "status", None) == ExecutionTaskState.CLAIMED.value:
                    task.status = ExecutionTaskState.QUEUED.value
                task.metadata_json = previous_metadata
                if task_id not in blocked_task_ids:
                    blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._claim_admission_blocker(
                        task_id=task.id,
                        code="claim_transition_failed",
                        message="Canonical queued-to-claimed transition or lease creation failed.",
                        state=getattr(task, "status", None),
                        details={"reason": str(exc)},
                    )
                )
                continue
            created_lease_count += 1
            claimed_task_ids.append(task_id)
            receipts.append(
                mission_route._worker_claim_receipt(
                    task=task,
                    previous_state=ExecutionTaskState.QUEUED.value,
                    current_state=ExecutionTaskState.CLAIMED.value,
                    lease=lease,
                    task_type=task_type or preview_task_types.get(task_id),
                    claimed_at=now,
                    idempotency_status="newly_claimed",
                )
            )

        for task_id in sorted(existing_claimed_ids - set(claimed_task_ids)):
            task = tasks_by_id.get(task_id)
            if task is None:
                continue
            active_leases = mission_route._active_worker_leases_for_task(lease_repo, task.id)
            current_lease = next((lease for lease in active_leases if lease.holder_identity == holder_identity), None)
            if (
                task.status in {ExecutionTaskState.CLAIMED.value, ExecutionTaskState.RUNNING.value}
                and current_lease is not None
            ):
                already_claimed_task_ids.append(task_id)
                blocked_task_ids = [
                    blocked_task_id for blocked_task_id in blocked_task_ids if blocked_task_id != task_id
                ]
                blockers = [blocker for blocker in blockers if str(blocker.get("task_id")) != task_id]
                stored_receipt = existing_receipts.get(task_id)
                current_state = str(getattr(task, "status", ExecutionTaskState.CLAIMED.value))
                receipts.append(
                    mission_route._worker_claim_receipt(
                        task=task,
                        previous_state=ExecutionTaskState.QUEUED.value,
                        current_state=current_state,
                        lease=current_lease,
                        task_type=mission_route._task_type_for_claim(task),
                        claimed_at=str(stored_receipt.get("claimed_at") if stored_receipt else now),
                        idempotency_status="already_claimed_by_current_admission",
                    )
                )
            elif active_leases:
                if task_id not in blocked_task_ids:
                    blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._claim_admission_blocker(
                        task_id=task.id,
                        code="task_claimed_by_different_active_lease",
                        message="Previously admitted task is now claimed by a different active lease owner.",
                        state=task.status,
                        details={"worker_lease_id": str(active_leases[0].id)},
                    )
                )

        if already_claimed_task_ids and not claimed_task_ids:
            blockers = [
                blocker
                for blocker in blockers
                if not (blocker.get("task_id") is None and blocker.get("code") == "worker_dispatch_readiness_blocked")
            ]

        materialization_reference = None
        queue_admission_reference = None
        dispatch_readiness_summary: dict[str, Any] = {}
        if preview.claim_preview_envelopes:
            source_references = preview.claim_preview_envelopes[0].source_references
            materialization_reference = source_references.get("materialization_reference")
            queue_admission_reference = source_references.get("queue_admission_reference")
            dispatch_readiness_summary = source_references.get("dispatch_readiness_summary") or {}
        else:
            materialization_reference = metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
            queue_admission_reference = metadata.get(MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY)

        final_admitted_ids = {str(task_id) for task_id in claimed_task_ids} | {
            str(task_id) for task_id in already_claimed_task_ids
        }
        blockers = [
            blocker
            for blocker in blockers
            if blocker.get("task_id") is None or str(blocker.get("task_id")) not in final_admitted_ids
        ]
        blocked_task_ids = [task_id for task_id in blocked_task_ids if str(task_id) not in final_admitted_ids]

        if final_admitted_ids and not blocked_task_ids:
            blockers = [blocker for blocker in blockers if blocker.get("task_id") is not None]

        status = mission_route._claim_admission_status(
            newly_claimed=claimed_task_ids,
            already_claimed=already_claimed_task_ids,
            blocked=blocked_task_ids,
            blockers=blockers,
        )
        previous_version = existing_admission.get("admission_version") if isinstance(existing_admission, dict) else None
        admission_version = int(previous_version or 0) + 1
        durable_claimed_task_ids = sorted(set(claimed_task_ids) | set(already_claimed_task_ids) | existing_claimed_ids)
        admission = {
            "schema_version": MISSION_WORKER_CLAIM_ADMISSION_SCHEMA_VERSION,
            "mission_id": str(mission_id),
            "tenant_id": tenant_id_str,
            "admission_status": status,
            "admission_version": admission_version,
            "claimed_task_ids": durable_claimed_task_ids,
            "already_claimed_task_ids": already_claimed_task_ids,
            "skipped_task_ids": skipped_task_ids,
            "blocked_task_ids": list(dict.fromkeys(blocked_task_ids)),
            "claim_receipts": receipts,
            "blockers": blockers,
            "warnings": warnings,
            "materialization_reference": materialization_reference,
            "queue_admission_reference": queue_admission_reference,
            "dispatch_readiness_summary": dispatch_readiness_summary,
            "worker_dispatch_eligibility_summary": {
                "preview_status": preview.preview_status,
                "eligible_task_ids": sorted(preview_ids),
                "blocked_task_ids": preview.blocked_task_ids,
                "skipped_task_ids": preview.skipped_task_ids,
                "blocker_count": len(preview.blockers),
                "warning_count": len(preview.warnings),
            },
            "worker_claim_preview_reference": {
                "preview_status": preview.preview_status,
                "preview_task_ids": sorted(preview_ids),
                "envelope_count": len(preview.claim_preview_envelopes),
                "checked_at": preview.checked_at,
            },
            "claim_admitted_by": admitted_by,
            "claim_admitted_at": now,
            "updated_at": now,
            "runtime_authority": mission_route._worker_claim_admission_authority_flags(
                creates_worker_leases=created_lease_count > 0, read_only=False
            ).model_dump(),
        }
        metadata[MISSION_WORKER_CLAIM_ADMISSION_METADATA_KEY] = admission
        mission_repo.update_metadata(mission=mission, metadata_json=metadata)
        return mission_route._worker_claim_admission_to_read(
            mission_id=mission_id, tenant_id=tenant_id_str, admission=admission
        )
