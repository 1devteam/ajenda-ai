from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.mission import (
    MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
    MISSION_WORKER_RUN_ADMISSION_METADATA_KEY,
    MISSION_WORKER_RUN_ADMISSION_SCHEMA_VERSION,
    MISSION_WORKER_START_ADMISSION_METADATA_KEY,
)
from backend.queue.base import QueueAdapter
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.worker_lease_repository import WorkerLeaseRepository
from backend.workers.task_dispatcher import TaskDispatcher


class WorkerRunAdmissionService:
    """Owns WorkerRunAdmissionService runtime bridge business logic."""

    def __init__(
        self,
        db: Session,
        queue: QueueAdapter,
        *,
        mission_repository_cls: Any = MissionRepository,
        execution_task_repository_cls: Any = ExecutionTaskRepository,
        worker_lease_repository_cls: Any = WorkerLeaseRepository,
        task_dispatcher_cls: Any = TaskDispatcher,
    ) -> None:
        self._db = db
        self._queue = queue
        self._mission_repository_cls = mission_repository_cls
        self._execution_task_repository_cls = execution_task_repository_cls
        self._worker_lease_repository_cls = worker_lease_repository_cls
        self._task_dispatcher_cls = task_dispatcher_cls

    def admit(self, *, mission_id: UUID, tenant_id: UUID, admitted_by: str, request: Any) -> Any:
        from backend.api.routes import mission as mission_route

        tenant_id_str = str(tenant_id)
        mission_repo = self._mission_repository_cls(self._db)
        mission = mission_repo.lock_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
        if mission is None:
            raise HTTPException(status_code=404, detail="mission not found for tenant")

        metadata = dict(mission.metadata_json or {})
        start_admission = metadata.get(MISSION_WORKER_START_ADMISSION_METADATA_KEY)
        existing_run = metadata.get(MISSION_WORKER_RUN_ADMISSION_METADATA_KEY)
        if not isinstance(existing_run, dict):
            existing_run = {}
        prior_run_receipts = [
            dict(receipt)
            for receipt in [
                *(existing_run.get("historical_run_receipts") or []),
                *(existing_run.get("run_receipts") or []),
            ]
            if isinstance(receipt, dict) and receipt.get("task_id") is not None
        ]
        now = datetime.now(UTC).isoformat()
        admitted_by = admitted_by

        task_repo = self._execution_task_repository_cls(self._db)
        lease_repo = self._worker_lease_repository_cls(self._db)
        tasks_by_id = {str(task.id): task for task in task_repo.list_for_mission(mission_id=mission_id)}

        executed_task_ids: list[str] = []
        completed_task_ids: list[str] = []
        failed_task_ids: list[str] = []
        already_completed_task_ids: list[str] = []
        already_failed_task_ids: list[str] = []
        skipped_task_ids: list[str] = []
        blocked_task_ids: list[str] = []
        run_receipts: list[dict[str, Any]] = []
        queue_claim_receipts: list[dict[str, Any]] = []
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        if not isinstance(start_admission, dict):
            blockers.append(
                mission_route._run_admission_blocker(
                    task_id=None,
                    code="worker_start_admission_missing",
                    message="Worker run admission requires current worker execution start admission metadata.",
                )
            )
            started_task_ids: list[str] = []
            start_receipts: dict[str, dict[str, Any]] = {}
        else:
            start_status = start_admission.get("admission_status")
            if start_status not in {"admitted", "partially_admitted"}:
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=None,
                        code="worker_start_admission_not_admitted",
                        message="Worker run admission requires admitted or partially admitted worker start metadata.",
                        details={"start_admission_status": str(start_status)},
                    )
                )
                started_task_ids = []
                start_receipts = {}
            else:
                started_task_ids = [str(task_id) for task_id in start_admission.get("started_task_ids") or []]
                start_receipts = {
                    str(receipt.get("task_id")): receipt
                    for receipt in start_admission.get("start_receipts") or []
                    if isinstance(receipt, dict) and receipt.get("task_id") is not None
                }
                if not started_task_ids:
                    blockers.append(
                        mission_route._run_admission_blocker(
                            task_id=None,
                            code="worker_start_admission_empty",
                            message="Worker start admission has no durable started_task_ids to run.",
                        )
                    )

        holder_identity = f"worker_claim_admission:{tenant_id_str}:{mission_id}"
        dispatcher_session_factory = mission_route._tenant_aware_dispatcher_session_factory(
            request=request, tenant_id=tenant_id_str
        )

        historical_run_receipts = [dict(receipt) for receipt in prior_run_receipts]

        for task_id in sorted(dict.fromkeys(started_task_ids)):
            task = tasks_by_id.get(task_id)
            start_receipt = start_receipts.get(task_id)
            if start_receipt is None:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task_id,
                        code="worker_start_receipt_missing",
                        message="Started task is missing a durable start receipt.",
                    )
                )
                continue
            if task is None:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task_id,
                        code="run_task_unavailable",
                        message="Started task is unavailable at run admission time.",
                    )
                )
                continue
            if task.tenant_id != tenant_id_str or task.mission_id != mission_id:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task.id,
                        code="run_task_scope_mismatch",
                        message="Run candidate is not owned by this tenant and mission.",
                        state=task.status,
                    )
                )
                continue
            task_type = mission_route._task_type_for_claim(task)
            if not task_type:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task.id,
                        code="run_task_missing_task_type",
                        message="Run admission requires explicit non-empty task_type metadata.",
                        state=task.status,
                    )
                )
                continue
            task_metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
            expected_lease_id = str(
                task_metadata.get("worker_lease_id") or mission_route._receipt_worker_lease_id(start_receipt)
            )
            if not expected_lease_id:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task.id,
                        code="worker_lease_id_missing",
                        message="Run admission requires a worker_lease_id in task metadata or start receipt.",
                        state=task.status,
                    )
                )
                continue
            try:
                lease_uuid = UUID(expected_lease_id)
            except ValueError:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task.id,
                        code="worker_lease_id_invalid",
                        message="Run admission requires a valid worker_lease_id.",
                        state=task.status,
                        details={"worker_lease_id": expected_lease_id},
                    )
                )
                continue

            started_from_admission_at = (
                str(start_receipt.get("started_at")) if start_receipt.get("started_at") else None
            )
            retry_count = mission_route._retry_count_for_run_attempt(task, start_receipt)
            existing_receipt = next(
                (
                    receipt
                    for receipt in prior_run_receipts
                    if receipt.get("idempotency_status")
                    in {
                        "newly_executed",
                        "already_completed_by_current_run_admission",
                        "already_failed_by_current_run_admission",
                    }
                    and mission_route._run_receipt_matches_attempt(
                        receipt=receipt,
                        task_id=task_id,
                        worker_lease_id=expected_lease_id,
                        started_from_admission_at=started_from_admission_at,
                        retry_count=retry_count,
                    )
                ),
                None,
            )
            if existing_receipt is not None:
                terminal_state = str(existing_receipt.get("current_task_state") or "")
                copied = dict(existing_receipt)
                if terminal_state == ExecutionTaskState.COMPLETED.value:
                    already_completed_task_ids.append(task_id)
                    copied["idempotency_status"] = "already_completed_by_current_run_admission"
                    run_receipts.append(copied)
                    historical_run_receipts = [
                        receipt for receipt in historical_run_receipts if receipt != existing_receipt
                    ]
                    continue
                if terminal_state in {ExecutionTaskState.FAILED.value, ExecutionTaskState.DEAD_LETTERED.value}:
                    already_failed_task_ids.append(task_id)
                    copied["idempotency_status"] = "already_failed_by_current_run_admission"
                    run_receipts.append(copied)
                    historical_run_receipts = [
                        receipt for receipt in historical_run_receipts if receipt != existing_receipt
                    ]
                    continue

            lease = lease_repo.get(lease_uuid)
            if lease is None:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task.id,
                        code="worker_lease_missing",
                        message="Run admission requires an existing WorkerLease.",
                        state=task.status,
                        details={"worker_lease_id": expected_lease_id},
                    )
                )
                continue
            if lease.tenant_id != tenant_id_str or lease.task_id != task.id:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task.id,
                        code="worker_lease_scope_mismatch",
                        message="WorkerLease must belong to the same tenant and task as the run candidate.",
                        state=task.status,
                        details={"worker_lease_id": str(lease.id)},
                    )
                )
                continue
            if lease.holder_identity != holder_identity:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task.id,
                        code="worker_lease_holder_mismatch",
                        message="WorkerLease holder does not match current worker claim admission owner.",
                        state=task.status,
                        details={"worker_lease_id": str(lease.id), "holder_identity": lease.holder_identity},
                    )
                )
                continue
            if lease.status != WorkerLeaseState.ACTIVE.value:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task.id,
                        code="worker_lease_inactive",
                        message="WorkerLease is not active for dispatcher execution.",
                        state=task.status,
                        details={"worker_lease_id": str(lease.id), "lease_status": lease.status},
                    )
                )
                continue
            if task.status != ExecutionTaskState.RUNNING.value:
                skipped_task_ids.append(task_id)
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task.id,
                        code="run_task_not_running",
                        message="Worker run admission only executes running tasks from current start admission.",
                        state=task.status,
                    )
                )
                continue

            claim_result = self._queue.claim_existing_task(
                tenant_id=tenant_id_str, task_id=task.id, worker_id=holder_identity
            )
            if not claim_result.ok:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task.id,
                        code="queue_claim_unavailable",
                        message="Queue payload could not be claimed into processing for dispatcher execution.",
                        state=task.status,
                        details={"reason": claim_result.reason},
                    )
                )
                continue
            queue_claim = {
                "claimed": True,
                "owner": holder_identity,
                "holder": holder_identity,
                "adapter": type(self._queue).__name__,
                "task_id": str(task.id),
                "claimed_at": now,
            }
            queue_claim_receipts.append(queue_claim)

            executed_at = datetime.now(UTC).isoformat()
            dispatcher = self._task_dispatcher_cls(
                session_factory=cast(Any, dispatcher_session_factory),
                queue=self._queue,
                worker_id=holder_identity,
                tenant_id=tenant_id_str,
            )
            try:
                dispatcher.execute(task_id=task.id, lease_id=lease.id)
            except Exception as exc:
                warnings.append({"code": "dispatcher_execute_raised", "task_id": str(task.id), "message": str(exc)})
            if hasattr(self._db, "expire_all"):
                self._db.expire_all()
            refreshed_task = task_repo.get(task.id) or task
            refreshed_lease = lease_repo.get(lease.id) or lease
            current_state = str(getattr(refreshed_task, "status", task.status))
            terminal_at = datetime.now(UTC).isoformat()
            receipt = mission_route._run_receipt(
                task=refreshed_task,
                previous_state=ExecutionTaskState.RUNNING.value,
                current_state=current_state,
                lease=refreshed_lease,
                queue_claim=queue_claim,
                task_type=task_type,
                started_from_admission_at=started_from_admission_at,
                retry_count=retry_count,
                executed_at=executed_at,
                completed_at=terminal_at if current_state == ExecutionTaskState.COMPLETED.value else None,
                failed_at=terminal_at
                if current_state in {ExecutionTaskState.FAILED.value, ExecutionTaskState.DEAD_LETTERED.value}
                else None,
                result_summary=mission_route._safe_run_summary(refreshed_task, handler_key=task_type),
                error_summary={"message": "handler failed or dispatcher marked task failed"}
                if current_state != ExecutionTaskState.COMPLETED.value
                else None,
                idempotency_status="newly_executed",
            )
            executed_task_ids.append(task_id)
            run_receipts.append(receipt)
            if current_state == ExecutionTaskState.COMPLETED.value:
                completed_task_ids.append(task_id)
            elif current_state in {ExecutionTaskState.FAILED.value, ExecutionTaskState.DEAD_LETTERED.value}:
                failed_task_ids.append(task_id)
            else:
                blocked_task_ids.append(task_id)
                blockers.append(
                    mission_route._run_admission_blocker(
                        task_id=task.id,
                        code="dispatcher_terminal_state_missing",
                        message="Dispatcher returned without a completed, failed, or dead-lettered task state.",
                        state=current_state,
                    )
                )

        status = mission_route._run_admission_status(
            completed=completed_task_ids,
            failed=failed_task_ids,
            already_completed=already_completed_task_ids,
            already_failed=already_failed_task_ids,
            blocked=list(dict.fromkeys(blocked_task_ids)),
        )
        previous_version = existing_run.get("admission_version") if isinstance(existing_run, dict) else None
        admission_version = int(previous_version or 0) + 1
        admission: dict[str, Any] = {
            "schema_version": MISSION_WORKER_RUN_ADMISSION_SCHEMA_VERSION,
            "mission_id": str(mission_id),
            "tenant_id": tenant_id_str,
            "admission_status": status,
            "admission_version": admission_version,
            "executed_task_ids": sorted(set(executed_task_ids) | set(existing_run.get("executed_task_ids") or [])),
            "completed_task_ids": sorted(set(completed_task_ids) | set(existing_run.get("completed_task_ids") or [])),
            "failed_task_ids": sorted(set(failed_task_ids) | set(existing_run.get("failed_task_ids") or [])),
            "already_completed_task_ids": already_completed_task_ids,
            "already_failed_task_ids": already_failed_task_ids,
            "skipped_task_ids": list(dict.fromkeys(skipped_task_ids)),
            "blocked_task_ids": list(dict.fromkeys(blocked_task_ids)),
            "run_receipts": run_receipts,
            "historical_run_receipts": historical_run_receipts,
            "blockers": blockers,
            "warnings": warnings,
            "queue_claim_receipts": queue_claim_receipts,
            "tenant_session_context": {"tenant_id": tenant_id_str, "rls_context_applied": True},
            "materialization_reference": start_admission.get("materialization_reference")
            if isinstance(start_admission, dict)
            else metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY),
            "queue_admission_reference": start_admission.get("queue_admission_reference")
            if isinstance(start_admission, dict)
            else metadata.get(MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY),
            "dispatch_readiness_summary": start_admission.get("dispatch_readiness_summary")
            if isinstance(start_admission, dict)
            else {},
            "worker_dispatch_eligibility_summary": start_admission.get("worker_dispatch_eligibility_summary")
            if isinstance(start_admission, dict)
            else {},
            "worker_claim_preview_reference": start_admission.get("worker_claim_preview_reference")
            if isinstance(start_admission, dict)
            else {},
            "worker_claim_admission_reference": start_admission.get("worker_claim_admission_reference")
            if isinstance(start_admission, dict)
            else {},
            "worker_start_admission_reference": {
                "admission_status": start_admission.get("admission_status")
                if isinstance(start_admission, dict)
                else None,
                "admission_version": start_admission.get("admission_version")
                if isinstance(start_admission, dict)
                else None,
                "started_task_ids": start_admission.get("started_task_ids")
                if isinstance(start_admission, dict)
                else [],
                "start_receipt_count": len(start_admission.get("start_receipts") or [])
                if isinstance(start_admission, dict)
                else 0,
                "updated_at": start_admission.get("updated_at") if isinstance(start_admission, dict) else None,
            },
            "run_admitted_by": admitted_by,
            "run_admitted_at": now,
            "updated_at": datetime.now(UTC).isoformat(),
            "runtime_authority": mission_route._worker_run_admission_authority_flags(
                read_only=False, completed=bool(completed_task_ids), failed=bool(failed_task_ids)
            ).model_dump(),
        }
        metadata[MISSION_WORKER_RUN_ADMISSION_METADATA_KEY] = admission
        mission_repo.update_metadata(mission=mission, metadata_json=metadata)
        return mission_route._worker_run_admission_to_read(
            mission_id=mission_id, tenant_id=tenant_id_str, admission=admission
        )
