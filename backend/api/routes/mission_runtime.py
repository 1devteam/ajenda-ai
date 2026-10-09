from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from backend.api.routes.mission_contracts import BridgeRuntimeAuthorityRead, RuntimeAdmissionRead
from backend.auth.permissions import Permission
from backend.domain.mission import (
    MISSION_RUNTIME_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
    MISSION_WORKER_CLAIM_ADMISSION_METADATA_KEY,
    MISSION_WORKER_RUN_ADMISSION_METADATA_KEY,
    MISSION_WORKER_START_ADMISSION_METADATA_KEY,
    Mission,
)
from backend.queue.base import QueueAdapter
from backend.services.mission_bridge import read_models as _mission_bridge_read_models
from backend.services.mission_bridge.materialization import (
    build_mission_runtime_readiness as _build_mission_runtime_readiness,
)
from backend.services.mission_bridge.materialization import (
    build_runtime_task_preview_items as _build_runtime_task_preview_items,
)
from backend.services.mission_bridge.materialization import (
    runtime_preview_authority_flags as _runtime_preview_authority_flags,
)
from backend.services.mission_bridge.materialization import (
    runtime_task_materialization_to_read as _runtime_task_materialization_to_read,
)
from backend.services.mission_bridge.worker_claim import (
    build_runtime_dispatch_readiness as _build_runtime_dispatch_readiness,
)
from backend.services.mission_bridge.worker_claim import (
    build_worker_claim_preview as _build_worker_claim_preview,
)
from backend.services.mission_bridge.worker_claim import (
    build_worker_dispatch_eligibility as _build_worker_dispatch_eligibility,
)
from backend.services.mission_bridge.worker_claim import (
    missing_worker_claim_admission as _missing_worker_claim_admission,
)
from backend.services.mission_bridge.worker_claim import (
    worker_claim_admission_to_read as _worker_claim_admission_to_read,
)
from backend.services.mission_bridge.worker_run import (
    missing_worker_run_admission as _missing_worker_run_admission,
)
from backend.services.mission_bridge.worker_run import (
    tenant_aware_dispatcher_session_factory as _tenant_aware_dispatcher_session_factory_impl,
)
from backend.services.mission_bridge.worker_run import (
    worker_run_admission_authority_flags as _worker_run_admission_authority_flags_impl,
)
from backend.services.mission_bridge.worker_run import (
    worker_run_admission_to_read as _worker_run_admission_to_read,
)
from backend.services.mission_bridge.worker_start import (
    missing_worker_start_admission as _missing_worker_start_admission,
)
from backend.services.mission_bridge.worker_start import (
    worker_start_admission_to_read as _worker_start_admission_to_read,
)
from backend.services.mission_runtime_queue_admission_service import (
    MissionRuntimeQueueAdmissionService as _MissionRuntimeQueueAdmissionService,
)
from backend.services.mission_runtime_task_materialization_service import (
    MissionRuntimeTaskMaterializationService as _MissionRuntimeTaskMaterializationService,
)

RuntimeReadinessStatus = _mission_bridge_read_models.RuntimeReadinessStatus
RuntimeReadinessCheckStatus = _mission_bridge_read_models.RuntimeReadinessCheckStatus
RuntimeReadinessItem = _mission_bridge_read_models.RuntimeReadinessItem
RuntimeReadinessRead = _mission_bridge_read_models.RuntimeReadinessRead
RuntimeTaskPreviewStatus = _mission_bridge_read_models.RuntimeTaskPreviewStatus
RuntimeTaskPreviewPayload = _mission_bridge_read_models.RuntimeTaskPreviewPayload
RuntimeTaskPreviewItem = _mission_bridge_read_models.RuntimeTaskPreviewItem
RuntimeTaskPreviewRead = _mission_bridge_read_models.RuntimeTaskPreviewRead
RuntimeTaskMaterializationStatus = _mission_bridge_read_models.RuntimeTaskMaterializationStatus
RuntimeDispatchReadinessStatus = _mission_bridge_read_models.RuntimeDispatchReadinessStatus
WorkerDispatchEligibilityStatus = _mission_bridge_read_models.WorkerDispatchEligibilityStatus
WorkerClaimPreviewStatus = _mission_bridge_read_models.WorkerClaimPreviewStatus
WorkerClaimAdmissionStatus = _mission_bridge_read_models.WorkerClaimAdmissionStatus
WorkerStartAdmissionStatus = _mission_bridge_read_models.WorkerStartAdmissionStatus
WorkerRunAdmissionStatus = _mission_bridge_read_models.WorkerRunAdmissionStatus
RuntimeTaskMaterializationRead = _mission_bridge_read_models.RuntimeTaskMaterializationRead
RuntimeDispatchAuthority = _mission_bridge_read_models.RuntimeDispatchAuthority
RuntimeDispatchReadinessRead = _mission_bridge_read_models.RuntimeDispatchReadinessRead
WorkerDispatchAuthority = _mission_bridge_read_models.WorkerDispatchAuthority
WorkerClaimAuthority = _mission_bridge_read_models.WorkerClaimAuthority
WorkerDispatchEligibilityRead = _mission_bridge_read_models.WorkerDispatchEligibilityRead
WorkerClaimPreviewEnvelope = _mission_bridge_read_models.WorkerClaimPreviewEnvelope
WorkerClaimPreviewRead = _mission_bridge_read_models.WorkerClaimPreviewRead
WorkerClaimReceipt = _mission_bridge_read_models.WorkerClaimReceipt
WorkerClaimAdmissionRead = _mission_bridge_read_models.WorkerClaimAdmissionRead
WorkerStartAuthority = _mission_bridge_read_models.WorkerStartAuthority
WorkerRunAuthority = _mission_bridge_read_models.WorkerRunAuthority
WorkerStartReceipt = _mission_bridge_read_models.WorkerStartReceipt
WorkerStartAdmissionRead = _mission_bridge_read_models.WorkerStartAdmissionRead
WorkerRunReceipt = _mission_bridge_read_models.WorkerRunReceipt
WorkerRunAdmissionRead = _mission_bridge_read_models.WorkerRunAdmissionRead
MissionRuntimeQueueAdmissionService = _MissionRuntimeQueueAdmissionService
MissionRuntimeTaskMaterializationService = _MissionRuntimeTaskMaterializationService
_tenant_aware_dispatcher_session_factory = _tenant_aware_dispatcher_session_factory_impl
_worker_run_admission_authority_flags = _worker_run_admission_authority_flags_impl


@dataclass(frozen=True)
class RuntimeRouteDependencies:
    mission_repository_cls: Any
    execution_task_repository_cls: Any
    capability_repository_cls: Any
    capability_adapter_repository_cls: Any
    outcome_review_repository_cls: Any
    task_materialization_service_cls: Any
    queue_admission_service_cls: Any
    quota_enforcement_service_cls: Any
    execution_coordinator_cls: Any
    provision_bridge_runtime_authority: Any
    require_route_permission: Any


def _runtime_admission_to_read(mission: Mission) -> RuntimeAdmissionRead:
    return RuntimeAdmissionRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        runtime_admission=mission.metadata_json.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY, {}),
        updated_at=mission.updated_at.isoformat(),
    )


def read_mission_runtime_readiness(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> RuntimeReadinessRead:
    """Validate read-only runtime admission readiness without runtime authority."""
    return _build_mission_runtime_readiness(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        mission_repository_cls=deps.mission_repository_cls,
        capability_repository_cls=deps.capability_repository_cls,
        capability_adapter_repository_cls=deps.capability_adapter_repository_cls,
        outcome_review_repository_cls=deps.outcome_review_repository_cls,
    )


def read_mission_runtime_task_preview(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> RuntimeTaskPreviewRead:
    """Preview future ExecutionTask materialization without creating or queueing work."""
    readiness = _build_mission_runtime_readiness(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        mission_repository_cls=deps.mission_repository_cls,
        capability_repository_cls=deps.capability_repository_cls,
        capability_adapter_repository_cls=deps.capability_adapter_repository_cls,
        outcome_review_repository_cls=deps.outcome_review_repository_cls,
    )
    tasks = _build_runtime_task_preview_items(mission_id=mission_id, readiness=readiness) if readiness.ready else []
    preview_status: RuntimeTaskPreviewStatus = readiness.readiness_status
    if readiness.ready and len(tasks) != readiness.selected_node_count:
        preview_status = "incomplete"
    readiness_summary = {
        "readiness_status": readiness.readiness_status,
        "selected_node_count": readiness.selected_node_count,
        "check_count": len(readiness.checks),
        "blocker_count": len(readiness.blockers),
        "warning_count": len(readiness.warnings),
    }
    return RuntimeTaskPreviewRead(
        mission_id=readiness.mission_id,
        tenant_id=readiness.tenant_id,
        ready=readiness.ready and preview_status == "ready",
        preview_status=preview_status,
        checked_at=readiness.checked_at,
        readiness_summary=readiness_summary,
        task_count=len(tasks),
        tasks=tasks,
        blockers=readiness.blockers,
        warnings=readiness.warnings,
        runtime_authority=_runtime_preview_authority_flags(),
    )


def read_mission_runtime_task_materialization(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> RuntimeTaskMaterializationRead:
    """Read tenant-scoped ExecutionTask materialization metadata."""
    mission = deps.mission_repository_cls(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    materialization = (mission.metadata_json or {}).get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
    if not isinstance(materialization, dict):
        raise HTTPException(status_code=404, detail="mission runtime task materialization not found")
    return _runtime_task_materialization_to_read(mission=mission, metadata=materialization)


def materialize_mission_runtime_tasks(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> RuntimeTaskMaterializationRead:
    """Create planned ExecutionTask rows from a ready admitted mission graph without queueing work."""
    deps.require_route_permission(request=request, db=db, permission=Permission.RUNTIME_OPERATE, tenant_id=tenant_id)
    return cast(
        RuntimeTaskMaterializationRead,
        deps.task_materialization_service_cls(
            db,
            mission_repository_cls=deps.mission_repository_cls,
            execution_task_repository_cls=deps.execution_task_repository_cls,
            capability_repository_cls=deps.capability_repository_cls,
            capability_adapter_repository_cls=deps.capability_adapter_repository_cls,
            outcome_review_repository_cls=deps.outcome_review_repository_cls,
        ).materialize(mission_id=mission_id, tenant_id=tenant_id),
    )


def read_mission_runtime_dispatch_readiness(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> RuntimeDispatchReadinessRead:
    """Read queued materialized task readiness without dispatching workers."""
    return _build_runtime_dispatch_readiness(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        mission_repository_cls=deps.mission_repository_cls,
        execution_task_repository_cls=deps.execution_task_repository_cls,
    )


def read_mission_worker_dispatch_eligibility(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> WorkerDispatchEligibilityRead:
    """Read worker dispatch eligibility without claiming leases or mutating runtime state."""
    return _build_worker_dispatch_eligibility(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        mission_repository_cls=deps.mission_repository_cls,
        execution_task_repository_cls=deps.execution_task_repository_cls,
    )


def read_mission_worker_claim_preview(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> WorkerClaimPreviewRead:
    """Preview future worker claim envelopes without claiming or dispatching work."""
    return _build_worker_claim_preview(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        mission_repository_cls=deps.mission_repository_cls,
        execution_task_repository_cls=deps.execution_task_repository_cls,
    )


def worker_claim_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> WorkerClaimAdmissionRead:
    """Deprecated: daemon workers exclusively own queue claim authority."""
    deps.require_route_permission(request=request, db=db, permission=Permission.RUNTIME_OPERATE, tenant_id=tenant_id)
    raise HTTPException(
        status_code=410,
        detail="HTTP worker claim admission was removed; queued work is claimed by the daemon worker.",
    )


def read_mission_worker_claim_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> WorkerClaimAdmissionRead:
    """Read latest worker claim admission metadata without mutating runtime state."""
    tenant_id_str = str(tenant_id)
    mission = deps.mission_repository_cls(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    metadata = mission.metadata_json if isinstance(mission.metadata_json, dict) else {}
    admission = metadata.get(MISSION_WORKER_CLAIM_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return _missing_worker_claim_admission(mission_id=mission_id, tenant_id=tenant_id_str)
    return _worker_claim_admission_to_read(
        mission_id=mission_id, tenant_id=tenant_id_str, admission=admission, read_only=True
    )


def worker_start_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> WorkerStartAdmissionRead:
    """Deprecated: daemon workers exclusively own execution start authority."""
    deps.require_route_permission(request=request, db=db, permission=Permission.RUNTIME_OPERATE, tenant_id=tenant_id)
    raise HTTPException(
        status_code=410,
        detail="HTTP worker start admission was removed; claimed work is started by the daemon worker.",
    )


def read_mission_worker_start_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> WorkerStartAdmissionRead:
    """Read latest worker execution start admission metadata without mutating runtime state."""
    tenant_id_str = str(tenant_id)
    mission = deps.mission_repository_cls(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    metadata = mission.metadata_json if isinstance(mission.metadata_json, dict) else {}
    admission = metadata.get(MISSION_WORKER_START_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return _missing_worker_start_admission(mission_id=mission_id, tenant_id=tenant_id_str)
    return _worker_start_admission_to_read(
        mission_id=mission_id, tenant_id=tenant_id_str, admission=admission, read_only=True
    )


def worker_run_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> WorkerRunAdmissionRead:
    """Deprecated: daemon workers exclusively own dispatcher execution authority."""
    deps.require_route_permission(request=request, db=db, permission=Permission.RUNTIME_OPERATE, tenant_id=tenant_id)
    raise HTTPException(
        status_code=410,
        detail="HTTP worker run admission was removed; running work is dispatched by the daemon worker.",
    )


def read_mission_worker_run_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> WorkerRunAdmissionRead:
    """Read latest worker run admission metadata without mutating runtime state."""
    tenant_id_str = str(tenant_id)
    mission = deps.mission_repository_cls(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    metadata = mission.metadata_json if isinstance(mission.metadata_json, dict) else {}
    admission = metadata.get(MISSION_WORKER_RUN_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return _missing_worker_run_admission(mission_id=mission_id, tenant_id=tenant_id_str)
    return _worker_run_admission_to_read(
        mission_id=mission_id, tenant_id=tenant_id_str, admission=admission, read_only=True
    )


def runtime_queue_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    queue: QueueAdapter,
    deps: RuntimeRouteDependencies,
) -> dict[str, object]:
    """Queue eligible planned tasks from the current runtime task materialization."""
    deps.require_route_permission(request=request, db=db, permission=Permission.EXECUTION_QUEUE, tenant_id=tenant_id)
    return admit_mission_runtime_queue(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        queue=queue,
        deps=deps,
    )


def read_mission_runtime_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> RuntimeAdmissionRead:
    """Read tenant-scoped graph-to-runtime admission metadata."""
    mission = deps.mission_repository_cls(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    if MISSION_RUNTIME_ADMISSION_METADATA_KEY not in (mission.metadata_json or {}):
        raise HTTPException(status_code=404, detail="mission runtime admission not found")
    return _runtime_admission_to_read(mission)


def provision_mission_bridge_runtime_authority(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID,
    db: Session,
    deps: RuntimeRouteDependencies,
) -> BridgeRuntimeAuthorityRead:
    """Provision tenant-scoped capability/adapter authority for mission bridge tool.invoke nodes."""
    deps.require_route_permission(request=request, db=db, permission=Permission.MISSION_MANAGE, tenant_id=tenant_id)
    principal = getattr(request.state, "principal", None)
    admitted_by = str(getattr(principal, "subject_id", "mission-bridge-ui")).strip() or "mission-bridge-ui"
    result = deps.provision_bridge_runtime_authority(
        db=db,
        mission_id=mission_id,
        tenant_id=tenant_id,
        admitted_by=admitted_by,
    )
    return BridgeRuntimeAuthorityRead.model_validate(result)


def admit_mission_runtime_queue(
    *,
    mission_id: UUID,
    tenant_id: _uuid.UUID,
    db: Session,
    queue: QueueAdapter,
    deps: RuntimeRouteDependencies,
) -> dict[str, object]:
    """Invoke the single canonical mission runtime queue-admission authority."""

    return cast(
        dict[str, object],
        deps.queue_admission_service_cls(
            db,
            queue,
            mission_repository_cls=deps.mission_repository_cls,
            execution_task_repository_cls=deps.execution_task_repository_cls,
            quota_enforcement_service_cls=deps.quota_enforcement_service_cls,
            execution_coordinator_cls=deps.execution_coordinator_cls,
        ).admit(mission_id=mission_id, tenant_id=tenant_id),
    )
