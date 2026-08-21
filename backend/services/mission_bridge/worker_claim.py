"""Worker claim admission and dispatch eligibility bridge helpers."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import (
    MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
    MISSION_WORKER_CLAIM_ADMISSION_SCHEMA_VERSION,
)
from backend.domain.worker_lease import WorkerLease
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.worker_lease_repository import WorkerLeaseRepository
from backend.services.mission_bridge.queue_admission import current_materialized_execution_task_ids
from backend.services.mission_bridge.read_models import (
    RuntimeDispatchAuthority,
    RuntimeDispatchReadinessRead,
    RuntimeDispatchReadinessStatus,
    WorkerClaimAdmissionRead,
    WorkerClaimAdmissionStatus,
    WorkerClaimAuthority,
    WorkerClaimPreviewEnvelope,
    WorkerClaimPreviewRead,
    WorkerClaimPreviewStatus,
    WorkerClaimReceipt,
    WorkerDispatchAuthority,
    WorkerDispatchEligibilityRead,
    WorkerDispatchEligibilityStatus,
)


def runtime_dispatch_authority_flags() -> RuntimeDispatchAuthority:
    return RuntimeDispatchAuthority(
        creates_execution_tasks=False,
        enqueues_work=False,
        dispatches_workers=False,
        calls_executor=False,
        calls_coordinator=False,
        executes_adapters=False,
        read_only=True,
    )


def runtime_dispatch_item(
    *, task_id: UUID | None, code: str, message: str, state: str | None = None, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": message}
    if task_id is not None:
        item["task_id"] = str(task_id)
    if state is not None:
        item["state"] = state
    if details:
        item["details"] = details
    return item


def queue_admission_status(metadata: dict[str, Any]) -> str | None:
    raw_status = metadata.get("admission_status") or metadata.get("queue_admission_status")
    return raw_status if isinstance(raw_status, str) else None


def uuid_set_from_metadata_list(metadata: dict[str, Any], key: str) -> set[UUID]:
    values = metadata.get(key)
    if not isinstance(values, list):
        return set()
    parsed: set[UUID] = set()
    for value in values:
        try:
            parsed.add(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return parsed


def task_has_dispatch_task_type(task: ExecutionTask) -> bool:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    task_type = metadata.get("task_type")
    return isinstance(task_type, str) and bool(task_type.strip())


def runtime_dispatch_readiness_status(
    *,
    dispatch_ready_task_ids: list[str],
    not_ready_task_ids: list[str],
    blocked_task_ids: list[str],
    skipped_task_ids: list[str],
) -> RuntimeDispatchReadinessStatus:
    if blocked_task_ids or not dispatch_ready_task_ids:
        if dispatch_ready_task_ids:
            return "partial"
        return "blocked"
    if not_ready_task_ids or skipped_task_ids:
        return "partial"
    return "ready"


def build_runtime_dispatch_readiness(
    *,
    mission_id: UUID,
    tenant_id: _uuid.UUID,
    db: Session,
    mission_repository_cls: Any = MissionRepository,
    execution_task_repository_cls: Any = ExecutionTaskRepository,
) -> RuntimeDispatchReadinessRead:
    """Build the read-only dispatch readiness contract for a tenant mission."""
    tenant_id_str = str(tenant_id)
    mission = mission_repository_cls(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    checked_at = datetime.now(UTC).isoformat()
    metadata = mission.metadata_json if isinstance(mission.metadata_json, dict) else {}
    materialization = metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
    queue_admission = metadata.get(MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY)
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    materialized_task_ids: list[UUID] = []
    if not isinstance(materialization, dict):
        blockers.append(
            runtime_dispatch_item(
                task_id=None,
                code="runtime_task_materialization_missing",
                message="Mission has no runtime task materialization metadata.",
            )
        )
        materialization_reference: dict[str, Any] | None = None
    else:
        materialization_reference = materialization
        materialized_task_ids = current_materialized_execution_task_ids(metadata)
        if not materialized_task_ids:
            blockers.append(
                runtime_dispatch_item(
                    task_id=None,
                    code="no_current_materialized_tasks",
                    message="Current runtime task materialization has no dispatchable execution task IDs.",
                )
            )

    queue_admitted_task_ids: set[UUID] = set()
    if not isinstance(queue_admission, dict):
        blockers.append(
            runtime_dispatch_item(
                task_id=None,
                code="runtime_queue_admission_missing",
                message="Mission has no runtime queue admission metadata.",
            )
        )
        queue_admission_reference: dict[str, Any] | None = None
    else:
        queue_admission_reference = queue_admission
        admission_status = queue_admission_status(queue_admission)
        if admission_status not in {"admitted", "partially_admitted"}:
            blockers.append(
                runtime_dispatch_item(
                    task_id=None,
                    code="runtime_queue_admission_not_admitted",
                    message="Runtime queue admission status is not admitted or partially admitted.",
                    details={"admission_status": admission_status},
                )
            )
        if queue_admission.get("tenant_id") not in {tenant_id_str, None}:
            blockers.append(
                runtime_dispatch_item(
                    task_id=None,
                    code="runtime_queue_admission_tenant_mismatch",
                    message="Runtime queue admission metadata belongs to a different tenant.",
                )
            )
        if queue_admission.get("mission_id") not in {str(mission_id), None}:
            blockers.append(
                runtime_dispatch_item(
                    task_id=None,
                    code="runtime_queue_admission_mission_mismatch",
                    message="Runtime queue admission metadata belongs to a different mission.",
                )
            )

        queue_materialized_task_ids = uuid_set_from_metadata_list(queue_admission, "materialized_execution_task_ids")
        current_materialized_task_ids = set(materialized_task_ids)
        if current_materialized_task_ids and queue_materialized_task_ids != current_materialized_task_ids:
            blockers.append(
                runtime_dispatch_item(
                    task_id=None,
                    code="queue_admission_materialization_mismatch",
                    message="Runtime queue admission does not cover the current runtime task materialization.",
                    details={
                        "current_materialized_task_ids": sorted(
                            str(task_id) for task_id in current_materialized_task_ids
                        ),
                        "queue_admission_materialized_task_ids": sorted(
                            str(task_id) for task_id in queue_materialized_task_ids
                        ),
                    },
                )
            )

        queue_admitted_task_ids = uuid_set_from_metadata_list(queue_admission, "admitted_execution_task_ids")

    task_repo = execution_task_repository_cls(db)
    tasks_by_id = {task.id: task for task in task_repo.list_for_mission(mission_id=mission_id)}
    dispatch_ready_task_ids: list[str] = []
    not_ready_task_ids: list[str] = []
    blocked_task_ids: list[str] = []
    skipped_task_ids: list[str] = []
    queued_task_count = 0

    for task_id in materialized_task_ids:
        task = tasks_by_id.get(task_id)
        if task is None:
            blocked_task_ids.append(str(task_id))
            blockers.append(
                runtime_dispatch_item(
                    task_id=task_id,
                    code="materialized_task_unavailable",
                    message="Materialized execution task row is missing or unavailable for this mission.",
                )
            )
            continue
        if task.tenant_id != tenant_id_str or task.mission_id != mission_id:
            blocked_task_ids.append(str(task_id))
            blockers.append(
                runtime_dispatch_item(
                    task_id=task_id,
                    code="materialized_task_scope_mismatch",
                    message="Materialized execution task is not owned by this tenant and mission.",
                    state=task.status,
                )
            )
            continue

        task_id_str = str(task.id)
        if task.status == ExecutionTaskState.QUEUED.value:
            queued_task_count += 1
            if task.id not in queue_admitted_task_ids:
                blocked_task_ids.append(task_id_str)
                blockers.append(
                    runtime_dispatch_item(
                        task_id=task.id,
                        code="task_not_queue_admitted",
                        message="Queued materialized task is not present in current runtime queue admission admitted task IDs.",
                        state=task.status,
                    )
                )
                continue
            if task_has_dispatch_task_type(task):
                dispatch_ready_task_ids.append(task_id_str)
                continue
            blocked_task_ids.append(task_id_str)
            blockers.append(
                runtime_dispatch_item(
                    task_id=task.id,
                    code="queued_task_missing_task_type",
                    message="Queued materialized task lacks non-empty dispatcher task_type metadata.",
                    state=task.status,
                )
            )
            warnings.append(
                runtime_dispatch_item(
                    task_id=task.id,
                    code="fallback_handler_not_allowed",
                    message="Dispatch readiness requires explicit task_type metadata; no fallback handler exists.",
                    state=task.status,
                )
            )
            continue
        if task.status in {ExecutionTaskState.PLANNED.value, ExecutionTaskState.PENDING_REVIEW.value}:
            not_ready_task_ids.append(task_id_str)
            blockers.append(
                runtime_dispatch_item(
                    task_id=task.id,
                    code="materialized_task_not_queued",
                    message="Materialized task has not been admitted to the runtime queue.",
                    state=task.status,
                )
            )
            continue
        if task.status in {
            ExecutionTaskState.CLAIMED.value,
            ExecutionTaskState.RUNNING.value,
            ExecutionTaskState.RECOVERING.value,
            ExecutionTaskState.BLOCKED.value,
        }:
            not_ready_task_ids.append(task_id_str)
            warnings.append(
                runtime_dispatch_item(
                    task_id=task.id,
                    code="materialized_task_already_claimed_or_running",
                    message="Materialized task is already claimed, running, recovering, or blocked.",
                    state=task.status,
                )
            )
            continue
        if task.status in {ExecutionTaskState.CANCELLED.value, ExecutionTaskState.COMPLETED.value}:
            skipped_task_ids.append(task_id_str)
            warnings.append(
                runtime_dispatch_item(
                    task_id=task.id,
                    code="materialized_task_terminal_skipped",
                    message="Terminal materialized task is not dispatchable and is skipped.",
                    state=task.status,
                )
            )
            continue
        if task.status in {ExecutionTaskState.FAILED.value, ExecutionTaskState.DEAD_LETTERED.value}:
            blocked_task_ids.append(task_id_str)
            blockers.append(
                runtime_dispatch_item(
                    task_id=task.id,
                    code="materialized_task_failed_or_dead_lettered",
                    message="Failed or dead-lettered materialized task is not dispatch-ready.",
                    state=task.status,
                )
            )
            continue

        blocked_task_ids.append(task_id_str)
        blockers.append(
            runtime_dispatch_item(
                task_id=task.id,
                code="materialized_task_unknown_state",
                message="Materialized task has an unknown runtime state.",
                state=task.status,
            )
        )

    readiness_status = runtime_dispatch_readiness_status(
        dispatch_ready_task_ids=dispatch_ready_task_ids,
        not_ready_task_ids=not_ready_task_ids,
        blocked_task_ids=blocked_task_ids,
        skipped_task_ids=skipped_task_ids,
    )
    precondition_blocker_codes = {
        "runtime_task_materialization_missing",
        "no_current_materialized_tasks",
        "runtime_queue_admission_missing",
        "runtime_queue_admission_not_admitted",
        "runtime_queue_admission_tenant_mismatch",
        "runtime_queue_admission_mission_mismatch",
        "queue_admission_materialization_mismatch",
    }
    if any(blocker.get("code") in precondition_blocker_codes for blocker in blockers):
        readiness_status = "blocked"
    elif blockers and readiness_status == "ready":
        readiness_status = "partial" if dispatch_ready_task_ids else "blocked"
    return RuntimeDispatchReadinessRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        readiness_status=readiness_status,
        dispatch_ready_task_ids=dispatch_ready_task_ids,
        not_ready_task_ids=not_ready_task_ids,
        blocked_task_ids=blocked_task_ids,
        skipped_task_ids=skipped_task_ids,
        task_count=len(materialized_task_ids),
        queued_task_count=queued_task_count,
        materialization_reference=materialization_reference,
        queue_admission_reference=queue_admission_reference,
        runtime_authority=runtime_dispatch_authority_flags(),
        blockers=blockers,
        warnings=warnings,
        checked_at=checked_at,
    )


def worker_dispatch_authority_flags() -> WorkerDispatchAuthority:
    return WorkerDispatchAuthority(
        creates_worker_leases=False,
        claims_tasks=False,
        starts_execution=False,
        dispatches_workers=False,
        executes_handlers=False,
        enqueues_work=False,
        mutates_runtime_state=False,
        read_only=True,
    )


def worker_claim_authority_flags() -> WorkerClaimAuthority:
    return WorkerClaimAuthority(
        creates_worker_leases=False,
        claims_tasks=False,
        starts_execution=False,
        dispatches_workers=False,
        executes_handlers=False,
        enqueues_work=False,
        mutates_runtime_state=False,
        read_only=True,
        preview_only=True,
    )


def worker_dispatch_eligibility_status(
    *, eligible_task_ids: list[str], ineligible_task_ids: list[str], readiness_status: str
) -> WorkerDispatchEligibilityStatus:
    if readiness_status == "blocked" or not eligible_task_ids:
        return "blocked"
    if ineligible_task_ids:
        return "partial"
    return "eligible"


def worker_claim_preview_status(eligibility_status: WorkerDispatchEligibilityStatus) -> WorkerClaimPreviewStatus:
    if eligibility_status == "eligible":
        return "ready"
    if eligibility_status == "partial":
        return "partial"
    return "blocked"


def worker_dispatch_summary(readiness: RuntimeDispatchReadinessRead) -> dict[str, Any]:
    return {
        "readiness_status": readiness.readiness_status,
        "dispatch_ready_task_ids": readiness.dispatch_ready_task_ids,
        "not_ready_task_ids": readiness.not_ready_task_ids,
        "blocked_task_ids": readiness.blocked_task_ids,
        "skipped_task_ids": readiness.skipped_task_ids,
        "task_count": readiness.task_count,
        "queued_task_count": readiness.queued_task_count,
        "blocker_count": len(readiness.blockers),
        "warning_count": len(readiness.warnings),
    }


def task_metadata_summary(task: ExecutionTask) -> dict[str, Any]:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    task_type = metadata.get("task_type")
    summary: dict[str, Any] = {"task_type": task_type if isinstance(task_type, str) else None}
    capability_reference = metadata.get("capability_reference")
    adapter_reference = metadata.get("adapter_reference")
    if isinstance(capability_reference, dict):
        summary["capability_reference"] = capability_reference
    if isinstance(adapter_reference, dict):
        summary["adapter_reference"] = adapter_reference
    for key in ("capability_id", "capability_name", "capability_version", "adapter_id", "graph_node_key"):
        value = metadata.get(key)
        if value is not None:
            summary[key] = value
    graph_node_reference = metadata.get("graph_node_reference")
    if isinstance(graph_node_reference, dict):
        summary["graph_node_reference"] = graph_node_reference
    return summary


def worker_claim_runtime_contract() -> dict[str, bool]:
    return {
        "requires_worker_lease": True,
        "requires_state_machine_transition": True,
        "requires_queue_claim": True,
        "requires_heartbeat": True,
        "requires_audit_event": True,
        "requires_lineage_or_evidence_capture": True,
    }


def build_worker_dispatch_eligibility(
    *,
    mission_id: UUID,
    tenant_id: _uuid.UUID,
    db: Session,
    mission_repository_cls: Any = MissionRepository,
    execution_task_repository_cls: Any = ExecutionTaskRepository,
) -> WorkerDispatchEligibilityRead:
    """Build read-only future worker claim eligibility from dispatch readiness."""
    readiness = build_runtime_dispatch_readiness(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        mission_repository_cls=mission_repository_cls,
        execution_task_repository_cls=execution_task_repository_cls,
    )
    tenant_id_str = str(tenant_id)
    mission = mission_repository_cls(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    metadata = mission.metadata_json if isinstance(mission.metadata_json, dict) else {}
    materialized_task_ids = current_materialized_execution_task_ids(metadata)
    materialized_task_id_set = set(materialized_task_ids)
    queue_admission = metadata.get(MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY)
    queue_materialized_task_ids = (
        uuid_set_from_metadata_list(queue_admission, "materialized_execution_task_ids")
        if isinstance(queue_admission, dict)
        else set()
    )
    queue_admitted_task_ids = (
        uuid_set_from_metadata_list(queue_admission, "admitted_execution_task_ids")
        if isinstance(queue_admission, dict)
        else set()
    )
    dispatch_ready_task_ids = {UUID(task_id) for task_id in readiness.dispatch_ready_task_ids}

    task_repo = execution_task_repository_cls(db)
    tasks_by_id = {task.id: task for task in task_repo.list_for_mission(mission_id=mission_id)}
    eligible_task_ids: list[str] = []
    ineligible_task_ids: list[str] = []
    blocked_task_ids: list[str] = []
    skipped_task_ids: list[str] = []
    blockers = [dict(item) for item in readiness.blockers]
    warnings = [dict(item) for item in readiness.warnings]

    for task_id in materialized_task_ids:
        task_id_str = str(task_id)
        task = tasks_by_id.get(task_id)
        task_blockers: list[dict[str, Any]] = []
        if task is None:
            task_blockers.append(
                runtime_dispatch_item(
                    task_id=task_id,
                    code="worker_task_unavailable",
                    message="Materialized task row is unavailable for future worker claim.",
                )
            )
        else:
            if task.tenant_id != tenant_id_str or task.mission_id != mission_id:
                task_blockers.append(
                    runtime_dispatch_item(
                        task_id=task.id,
                        code="worker_task_scope_mismatch",
                        message="Task is not owned by this tenant and mission and cannot be claimed by a worker.",
                        state=task.status,
                    )
                )
            if task_id not in materialized_task_id_set:
                task_blockers.append(
                    runtime_dispatch_item(
                        task_id=task.id,
                        code="worker_task_not_currently_materialized",
                        message="Task is not part of the current runtime task materialization.",
                        state=task.status,
                    )
                )
            if task_id not in queue_materialized_task_ids:
                task_blockers.append(
                    runtime_dispatch_item(
                        task_id=task.id,
                        code="worker_task_not_queue_materialized",
                        message="Task is not listed in current queue admission materialized task IDs.",
                        state=task.status,
                    )
                )
            if task_id not in queue_admitted_task_ids:
                task_blockers.append(
                    runtime_dispatch_item(
                        task_id=task.id,
                        code="worker_task_not_queue_admitted",
                        message="Task is not listed in current queue admission admitted task IDs.",
                        state=task.status,
                    )
                )
            if task_id not in dispatch_ready_task_ids:
                task_blockers.append(
                    runtime_dispatch_item(
                        task_id=task.id,
                        code="worker_task_not_dispatch_ready",
                        message="Task is not present in runtime dispatch readiness dispatch_ready_task_ids.",
                        state=task.status,
                    )
                )
            if task.status != ExecutionTaskState.QUEUED.value:
                task_blockers.append(
                    runtime_dispatch_item(
                        task_id=task.id,
                        code="worker_task_not_queued",
                        message="Future worker claim eligibility requires the task to remain queued.",
                        state=task.status,
                    )
                )
            if not task_has_dispatch_task_type(task):
                task_blockers.append(
                    runtime_dispatch_item(
                        task_id=task.id,
                        code="worker_task_missing_task_type",
                        message="Future worker claim eligibility requires explicit non-empty task_type metadata.",
                        state=task.status,
                    )
                )

        if task_blockers:
            ineligible_task_ids.append(task_id_str)
            blockers.extend(task_blockers)
            if task is not None and task.status in {
                ExecutionTaskState.CANCELLED.value,
                ExecutionTaskState.COMPLETED.value,
            }:
                skipped_task_ids.append(task_id_str)
            else:
                blocked_task_ids.append(task_id_str)
            continue
        eligible_task_ids.append(task_id_str)

    if readiness.readiness_status == "blocked":
        blockers.append(
            runtime_dispatch_item(
                task_id=None,
                code="worker_dispatch_readiness_blocked",
                message="Worker dispatch eligibility requires runtime dispatch readiness to be ready or partial.",
                details={"readiness_status": readiness.readiness_status},
            )
        )
        if eligible_task_ids:
            blocked_task_ids.extend(eligible_task_ids)
            ineligible_task_ids.extend(eligible_task_ids)
            eligible_task_ids = []

    eligibility_status = worker_dispatch_eligibility_status(
        eligible_task_ids=eligible_task_ids,
        ineligible_task_ids=ineligible_task_ids,
        readiness_status=readiness.readiness_status,
    )
    return WorkerDispatchEligibilityRead(
        mission_id=readiness.mission_id,
        tenant_id=readiness.tenant_id,
        eligibility_status=eligibility_status,
        eligible_task_ids=eligible_task_ids,
        ineligible_task_ids=ineligible_task_ids,
        blocked_task_ids=blocked_task_ids,
        skipped_task_ids=skipped_task_ids,
        task_count=readiness.task_count,
        queued_task_count=readiness.queued_task_count,
        materialization_reference=readiness.materialization_reference,
        queue_admission_reference=readiness.queue_admission_reference,
        dispatch_readiness_summary=worker_dispatch_summary(readiness),
        worker_dispatch_authority=worker_dispatch_authority_flags(),
        blockers=blockers,
        warnings=warnings,
        checked_at=datetime.now(UTC).isoformat(),
    )


def build_worker_claim_preview(
    *,
    mission_id: UUID,
    tenant_id: _uuid.UUID,
    db: Session,
    mission_repository_cls: Any = MissionRepository,
    execution_task_repository_cls: Any = ExecutionTaskRepository,
) -> WorkerClaimPreviewRead:
    """Build read-only future worker claim envelopes from eligibility."""
    eligibility = build_worker_dispatch_eligibility(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        mission_repository_cls=mission_repository_cls,
        execution_task_repository_cls=execution_task_repository_cls,
    )
    task_repo = execution_task_repository_cls(db)
    tasks_by_id = {str(task.id): task for task in task_repo.list_for_mission(mission_id=mission_id)}
    source_references = {
        "materialization_reference": eligibility.materialization_reference,
        "queue_admission_reference": eligibility.queue_admission_reference,
        "dispatch_readiness_summary": eligibility.dispatch_readiness_summary,
    }
    envelopes: list[WorkerClaimPreviewEnvelope] = []
    for task_id in eligibility.eligible_task_ids:
        task = tasks_by_id.get(task_id)
        if task is None:
            continue
        metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
        raw_task_type = metadata.get("task_type")
        task_type = raw_task_type.strip() if isinstance(raw_task_type, str) else ""
        envelopes.append(
            WorkerClaimPreviewEnvelope(
                task_id=task_id,
                tenant_id=task.tenant_id,
                mission_id=str(task.mission_id),
                task_type=task_type,
                current_task_state=task.status,
                expected_claim_from_state=ExecutionTaskState.QUEUED.value,
                future_claim_state=ExecutionTaskState.CLAIMED.value,
                worker_lease_required=True,
                lease_scope={"tenant_id": task.tenant_id, "mission_id": str(task.mission_id), "task_id": task_id},
                runtime_contract=worker_claim_runtime_contract(),
                source_references=source_references,
                task_metadata_summary=task_metadata_summary(task),
                preview_only=True,
            )
        )

    return WorkerClaimPreviewRead(
        mission_id=eligibility.mission_id,
        tenant_id=eligibility.tenant_id,
        preview_status=worker_claim_preview_status(eligibility.eligibility_status),
        claim_preview_envelopes=envelopes,
        blocked_task_ids=eligibility.blocked_task_ids,
        skipped_task_ids=eligibility.skipped_task_ids,
        blockers=eligibility.blockers,
        warnings=eligibility.warnings,
        worker_claim_authority=worker_claim_authority_flags(),
        checked_at=datetime.now(UTC).isoformat(),
    )


def worker_claim_admission_authority_flags(
    *, creates_worker_leases: bool, read_only: bool = False
) -> WorkerClaimAuthority:
    return WorkerClaimAuthority(
        creates_worker_leases=creates_worker_leases,
        claims_tasks=not read_only,
        starts_execution=False,
        dispatches_workers=False,
        executes_handlers=False,
        enqueues_work=False,
        mutates_runtime_state=not read_only,
        read_only=read_only,
        preview_only=False,
    )


def active_worker_leases_for_task(lease_repo: WorkerLeaseRepository, task_id: UUID) -> list[WorkerLease]:
    leases = lease_repo.list_for_task(task_id)
    return [
        lease
        for lease in leases
        if getattr(lease, "status", None) in {WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value}
    ]


def task_type_for_claim(task: ExecutionTask) -> str:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    raw_task_type = metadata.get("task_type")
    return raw_task_type.strip() if isinstance(raw_task_type, str) else ""


def claim_admission_blocker(
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


def worker_claim_receipt(
    *,
    task: ExecutionTask,
    previous_state: str,
    current_state: str,
    lease: WorkerLease | None,
    task_type: str | None,
    claimed_at: str,
    idempotency_status: Literal["newly_claimed", "already_claimed_by_current_admission", "blocked"],
) -> dict[str, Any]:
    return {
        "task_id": str(task.id),
        "tenant_id": task.tenant_id,
        "mission_id": str(task.mission_id),
        "previous_task_state": previous_state,
        "current_task_state": current_state,
        "worker_lease_id": str(lease.id) if lease is not None else None,
        "lease_scope": {"tenant_id": task.tenant_id, "mission_id": str(task.mission_id), "task_id": str(task.id)},
        "claim_source": "worker_claim_admission",
        "task_type": task_type,
        "claimed_at": claimed_at,
        "idempotency_status": idempotency_status,
    }


def claim_admission_status(
    *, newly_claimed: list[str], already_claimed: list[str], blocked: list[str], blockers: list[dict[str, Any]]
) -> WorkerClaimAdmissionStatus:
    admitted_count = len(newly_claimed) + len(already_claimed)
    if admitted_count and (blocked or blockers):
        return "partially_admitted"
    if admitted_count:
        return "admitted"
    return "blocked"


def worker_claim_admission_to_read(
    *, mission_id: UUID, tenant_id: str, admission: dict[str, Any], read_only: bool = False
) -> WorkerClaimAdmissionRead:
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
            "preview_only": False,
        }
    return WorkerClaimAdmissionRead(
        mission_id=mission_id,
        tenant_id=tenant_id,
        claim_admission_status=status,
        claimed_task_ids=list(admission.get("claimed_task_ids") or []),
        already_claimed_task_ids=list(admission.get("already_claimed_task_ids") or []),
        skipped_task_ids=list(admission.get("skipped_task_ids") or []),
        blocked_task_ids=list(admission.get("blocked_task_ids") or []),
        claim_receipts=[WorkerClaimReceipt(**receipt) for receipt in admission.get("claim_receipts") or []],
        blockers=list(admission.get("blockers") or []),
        warnings=list(admission.get("warnings") or []),
        worker_claim_authority=WorkerClaimAuthority(**authority),
        worker_claim_admission=admission,
        updated_at=str(admission.get("updated_at") or datetime.now(UTC).isoformat()),
    )


def missing_worker_claim_admission(*, mission_id: UUID, tenant_id: str) -> WorkerClaimAdmissionRead:
    now = datetime.now(UTC).isoformat()
    admission = {
        "schema_version": MISSION_WORKER_CLAIM_ADMISSION_SCHEMA_VERSION,
        "mission_id": str(mission_id),
        "tenant_id": tenant_id,
        "admission_status": "blocked",
        "admission_version": None,
        "claimed_task_ids": [],
        "already_claimed_task_ids": [],
        "skipped_task_ids": [],
        "blocked_task_ids": [],
        "claim_receipts": [],
        "blockers": [
            claim_admission_blocker(
                task_id=None,
                code="worker_claim_admission_missing",
                message="Mission has no worker claim admission metadata.",
            )
        ],
        "warnings": [],
        "runtime_authority": worker_claim_admission_authority_flags(
            creates_worker_leases=False, read_only=True
        ).model_dump(),
        "updated_at": now,
    }
    return worker_claim_admission_to_read(
        mission_id=mission_id, tenant_id=tenant_id, admission=admission, read_only=True
    )
