from __future__ import annotations

import hashlib
import json
import logging
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.api.routes import mission_contracts as _mission_contracts
from backend.api.routes import mission_runtime as _mission_runtime
from backend.api.routes._authorization import require_route_permission
from backend.app.config import get_settings
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.permissions import Permission
from backend.domain.enums import MissionPlanStatus, MissionState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import (
    MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
    MISSION_INTAKE_METADATA_KEY,
    MISSION_PLAN_METADATA_KEY,
    MISSION_RUNTIME_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
    MISSION_TASK_GRAPH_METADATA_KEY,
    MISSION_WORKER_CLAIM_ADMISSION_METADATA_KEY,
    MISSION_WORKER_RUN_ADMISSION_METADATA_KEY,
    MISSION_WORKER_START_ADMISSION_METADATA_KEY,
    Mission,
    MissionPlan,
    build_graph_materialization_metadata,
    build_mission_intake_metadata,
    build_mission_plan_contract_metadata,
    build_mission_plan_contract_metadata_from_legacy_write,
    build_mission_task_graph_contract_metadata,
    build_runtime_admission_metadata,
    legacy_mission_plan_status_from_planning_status,
    mission_task_graph_allows_legacy_v1,
    normalize_mission_plan_contract_metadata,
    normalize_mission_task_graph_contract_metadata,
    validate_mission_plan_status_transition,
)
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueAdapter
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_plan_repository import MissionPlanRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.outcome_review_repository import OutcomeReviewRepository
from backend.repositories.retrieval_contract_repository import RetrievalContractRepository
from backend.services.execution_coordinator import ExecutionCoordinator

# --- mission_bridge re-exports (Phase 1b layering) ---
from backend.services.mission_bridge.quota import quota_exceeded_response as _quota_exceeded_response
from backend.services.mission_bridge_runtime_authority import provision_bridge_runtime_authority
from backend.services.mission_composition.deliverable_runtime_observability import (
    build_deliverable_runtime_state_read,
)
from backend.services.mission_executor import MissionExecutor  # noqa: F401 - legacy test/patch compatibility
from backend.services.mission_graph_integrity import evaluate_admission_integrity
from backend.services.mission_intake_quality import (
    MissionIntakeQualityDeniedError,
    contains_composition_clarification,
    validate_mission_intake_prompt,
)
from backend.services.mission_runtime_projection import (
    supersede_runtime_task_materialization,
)
from backend.services.quota_enforcement import BudgetGateDeniedError, QuotaEnforcementService, QuotaExceededError
from backend.services.worker_runtime_service import WorkerRuntimeService

RuntimeReadinessStatus = _mission_runtime.RuntimeReadinessStatus
RuntimeReadinessCheckStatus = _mission_runtime.RuntimeReadinessCheckStatus
RuntimeReadinessItem = _mission_runtime.RuntimeReadinessItem
RuntimeReadinessRead = _mission_runtime.RuntimeReadinessRead
RuntimeTaskPreviewStatus = _mission_runtime.RuntimeTaskPreviewStatus
RuntimeTaskPreviewPayload = _mission_runtime.RuntimeTaskPreviewPayload
RuntimeTaskPreviewItem = _mission_runtime.RuntimeTaskPreviewItem
RuntimeTaskPreviewRead = _mission_runtime.RuntimeTaskPreviewRead
RuntimeTaskMaterializationStatus = _mission_runtime.RuntimeTaskMaterializationStatus
RuntimeDispatchReadinessStatus = _mission_runtime.RuntimeDispatchReadinessStatus
WorkerDispatchEligibilityStatus = _mission_runtime.WorkerDispatchEligibilityStatus
WorkerClaimPreviewStatus = _mission_runtime.WorkerClaimPreviewStatus
WorkerClaimAdmissionStatus = _mission_runtime.WorkerClaimAdmissionStatus
WorkerStartAdmissionStatus = _mission_runtime.WorkerStartAdmissionStatus
WorkerRunAdmissionStatus = _mission_runtime.WorkerRunAdmissionStatus
RuntimeTaskMaterializationRead = _mission_runtime.RuntimeTaskMaterializationRead
RuntimeDispatchAuthority = _mission_runtime.RuntimeDispatchAuthority
RuntimeDispatchReadinessRead = _mission_runtime.RuntimeDispatchReadinessRead
WorkerDispatchAuthority = _mission_runtime.WorkerDispatchAuthority
WorkerClaimAuthority = _mission_runtime.WorkerClaimAuthority
WorkerDispatchEligibilityRead = _mission_runtime.WorkerDispatchEligibilityRead
WorkerClaimPreviewEnvelope = _mission_runtime.WorkerClaimPreviewEnvelope
WorkerClaimPreviewRead = _mission_runtime.WorkerClaimPreviewRead
WorkerClaimReceipt = _mission_runtime.WorkerClaimReceipt
WorkerClaimAdmissionRead = _mission_runtime.WorkerClaimAdmissionRead
WorkerStartAuthority = _mission_runtime.WorkerStartAuthority
WorkerRunAuthority = _mission_runtime.WorkerRunAuthority
WorkerStartReceipt = _mission_runtime.WorkerStartReceipt
WorkerStartAdmissionRead = _mission_runtime.WorkerStartAdmissionRead
WorkerRunReceipt = _mission_runtime.WorkerRunReceipt
WorkerRunAdmissionRead = _mission_runtime.WorkerRunAdmissionRead
MissionRuntimeQueueAdmissionService = _mission_runtime.MissionRuntimeQueueAdmissionService
MissionRuntimeTaskMaterializationService = _mission_runtime.MissionRuntimeTaskMaterializationService


router = APIRouter(prefix="/missions", tags=["missions"])
logger = logging.getLogger("ajenda.mission_routes")

# Preserve the established backend.api.routes.mission import surface while the
# declarative request/response contracts live in their own module.
MissionPriority = _mission_contracts.MissionPriority
MissionPlanningStatus = _mission_contracts.MissionPlanningStatus
MissionRiskLevel = _mission_contracts.MissionRiskLevel
MissionApprovalGateStatus = _mission_contracts.MissionApprovalGateStatus
GraphMaterializationStatus = _mission_contracts.GraphMaterializationStatus
GraphOperatorReviewStatus = _mission_contracts.GraphOperatorReviewStatus
GraphValidationStatus = _mission_contracts.GraphValidationStatus
GraphValidationCheckStatus = _mission_contracts.GraphValidationCheckStatus
GraphGenerationMode = _mission_contracts.GraphGenerationMode
RuntimeAdmissionStatus = _mission_contracts.RuntimeAdmissionStatus
MissionSuccessCriterion = _mission_contracts.MissionSuccessCriterion
MissionConstraint = _mission_contracts.MissionConstraint
MissionBudgetLimits = _mission_contracts.MissionBudgetLimits
MissionCreate = _mission_contracts.MissionCreate
MissionPlanStage = _mission_contracts.MissionPlanStage
MissionPlanPhase = _mission_contracts.MissionPlanPhase
MissionDesiredOutput = _mission_contracts.MissionDesiredOutput
MissionCapabilityRequirement = _mission_contracts.MissionCapabilityRequirement
MissionApprovalGate = _mission_contracts.MissionApprovalGate
MissionEstimatedScope = _mission_contracts.MissionEstimatedScope
MissionRiskAnnotation = _mission_contracts.MissionRiskAnnotation
MissionPlanWrite = _mission_contracts.MissionPlanWrite
MissionPlanStep = _mission_contracts.MissionPlanStep
MissionPlanCreate = _mission_contracts.MissionPlanCreate
MissionTaskGraphRead = _mission_contracts.MissionTaskGraphRead
GraphPlannerProvenance = _mission_contracts.GraphPlannerProvenance
GraphCapabilitySelectionProvenance = _mission_contracts.GraphCapabilitySelectionProvenance
GraphValidationCheck = _mission_contracts.GraphValidationCheck
GraphValidationResult = _mission_contracts.GraphValidationResult
GraphOperatorReview = _mission_contracts.GraphOperatorReview
GraphGenerationMetadata = _mission_contracts.GraphGenerationMetadata
DeterministicCompilationMetadata = _mission_contracts.DeterministicCompilationMetadata
GraphMaterializationWrite = _mission_contracts.GraphMaterializationWrite
GraphMaterializationRead = _mission_contracts.GraphMaterializationRead
RuntimeAdmissionNodeSelection = _mission_contracts.RuntimeAdmissionNodeSelection
RuntimeAdmissionWrite = _mission_contracts.RuntimeAdmissionWrite
RuntimeAdmissionRead = _mission_contracts.RuntimeAdmissionRead
MissionPlanRead = _mission_contracts.MissionPlanRead
MissionRead = _mission_contracts.MissionRead
MissionListItem = _mission_contracts.MissionListItem
MissionListResponse = _mission_contracts.MissionListResponse
MissionLifecycleCompleteness = _mission_contracts.MissionLifecycleCompleteness
MissionLifecycleMissionSummary = _mission_contracts.MissionLifecycleMissionSummary
MissionLifecycleEvidenceItem = _mission_contracts.MissionLifecycleEvidenceItem
MissionLifecycleEvidenceSummary = _mission_contracts.MissionLifecycleEvidenceSummary
MissionLifecycleOutcomeReviewItem = _mission_contracts.MissionLifecycleOutcomeReviewItem
MissionLifecycleOutcomeReviewSummary = _mission_contracts.MissionLifecycleOutcomeReviewSummary
MissionLifecycleMemoryPromotionSummary = _mission_contracts.MissionLifecycleMemoryPromotionSummary
MissionLifecycleRetrievalContractItem = _mission_contracts.MissionLifecycleRetrievalContractItem
MissionLifecycleRetrievalContractSummary = _mission_contracts.MissionLifecycleRetrievalContractSummary
MissionLifecycleRead = _mission_contracts.MissionLifecycleRead
MissionTimelineEvent = _mission_contracts.MissionTimelineEvent
MissionTimelineRead = _mission_contracts.MissionTimelineRead
MissionQueueResponse = _mission_contracts.MissionQueueResponse
RuntimeQueueAdmissionResponse = _mission_contracts.RuntimeQueueAdmissionResponse
BridgeRuntimeAuthorityNode = _mission_contracts.BridgeRuntimeAuthorityNode
BridgeRuntimeAuthorityRead = _mission_contracts.BridgeRuntimeAuthorityRead
MissionCompileRequest = _mission_contracts.MissionCompileRequest
MissionCompileResponse = _mission_contracts.MissionCompileResponse
MissionLaunchResponse = _mission_contracts.MissionLaunchResponse
MissionCancelRequest = _mission_contracts.MissionCancelRequest


def _runtime_route_dependencies() -> _mission_runtime.RuntimeRouteDependencies:
    return _mission_runtime.RuntimeRouteDependencies(
        mission_repository_cls=MissionRepository,
        execution_task_repository_cls=ExecutionTaskRepository,
        capability_repository_cls=CapabilityRepository,
        capability_adapter_repository_cls=CapabilityAdapterRepository,
        outcome_review_repository_cls=OutcomeReviewRepository,
        task_materialization_service_cls=MissionRuntimeTaskMaterializationService,
        queue_admission_service_cls=MissionRuntimeQueueAdmissionService,
        quota_enforcement_service_cls=QuotaEnforcementService,
        execution_coordinator_cls=ExecutionCoordinator,
        provision_bridge_runtime_authority=provision_bridge_runtime_authority,
    )


_CLIENT_FORGED_ADMISSION_IDENTITIES = frozenset(
    {
        "mission-dispatch-ui",
        "mission_dispatch_ui",
        "dispatch-ui-v1",
        "mission-bridge-ui",
        "mission-dispatch",
    }
)


def _server_admitted_by(*, request: Request, body_admitted_by: str | None) -> str:
    """Prefer authenticated principal; never accept browser UI forged identities as authority."""
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        for attr in ("subject_id", "subject", "sub"):
            value = getattr(principal, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
    candidate = (body_admitted_by or "").strip()
    if candidate and candidate.lower() not in _CLIENT_FORGED_ADMISSION_IDENTITIES:
        return candidate
    return "server:runtime_admission"


def _task_graph_fingerprint(
    *,
    mission_id: str,
    graph_status: str | None,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    operator_notes: str | None,
) -> str:
    graph_identity = {
        "schema_version": 1,
        "mission_id": mission_id,
        "graph_status": graph_status,
        "nodes": nodes,
        "edges": edges,
        "operator_notes": operator_notes,
    }
    encoded = json.dumps(graph_identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _task_graph_contract_content(task_graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": task_graph["schema_version"],
        "graph_status": task_graph["graph_status"],
        "nodes": task_graph["nodes"],
        "edges": task_graph["edges"],
        "metadata": task_graph["metadata"],
    }


def _task_graph_has_identity(task_graph: dict[str, Any]) -> bool:
    return (
        isinstance(task_graph.get("mission_id"), str)
        and isinstance(task_graph.get("graph_version"), int)
        and isinstance(task_graph.get("graph_fingerprint"), str)
    )


def _task_graph_contract_fingerprint(*, mission_id: str, normalized_graph: dict[str, Any]) -> str:
    graph_identity = {"mission_id": mission_id, **_task_graph_contract_content(normalized_graph)}
    encoded = json.dumps(graph_identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _task_graph_with_identity(
    *, mission_id: UUID, normalized_graph: dict[str, Any], graph_version: int
) -> dict[str, Any]:
    mission_id_str = str(mission_id)
    graph_with_identity = {
        **_task_graph_contract_content(normalized_graph),
        "mission_id": mission_id_str,
        "graph_version": graph_version,
    }
    graph_with_identity["graph_fingerprint"] = _task_graph_contract_fingerprint(
        mission_id=mission_id_str, normalized_graph=graph_with_identity
    )
    return graph_with_identity


def _fingerprint_existing_task_graph(task_graph: dict[str, Any]) -> str | None:
    nodes = task_graph.get("nodes")
    edges = task_graph.get("edges")
    mission_id = task_graph.get("mission_id")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not isinstance(mission_id, str):
        return None
    if not all(isinstance(node, dict) for node in nodes) or not all(isinstance(edge, dict) for edge in edges):
        return None
    return _task_graph_fingerprint(
        mission_id=mission_id,
        graph_status=task_graph.get("graph_status") if isinstance(task_graph.get("graph_status"), str) else None,
        nodes=nodes,
        edges=edges,
        operator_notes=task_graph.get("operator_notes") if isinstance(task_graph.get("operator_notes"), str) else None,
    )


def _next_task_graph_version(existing_graph: Any) -> int:
    if not isinstance(existing_graph, dict):
        return 1
    version = existing_graph.get("graph_version")
    if not isinstance(version, int) or version < 1:
        return 1
    return version + 1


def _supersede_graph_materialization(
    *,
    metadata: dict[str, Any],
    graph_version: int,
    graph_fingerprint: str,
    updated_at: str,
) -> None:
    materialization = metadata.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    if not isinstance(materialization, dict):
        return
    superseded = dict(materialization)
    superseded["materialization_status"] = "superseded"
    superseded["updated_at"] = updated_at
    superseded["superseded_at"] = updated_at
    superseded["superseded_reason"] = "task_graph_replaced"
    superseded["superseded_by_graph_version"] = graph_version
    superseded["superseded_by_graph_fingerprint"] = graph_fingerprint
    metadata[MISSION_GRAPH_MATERIALIZATION_METADATA_KEY] = superseded


def _supersede_runtime_admission(
    *,
    metadata: dict[str, Any],
    graph_version: int,
    graph_fingerprint: str,
    updated_at: str,
) -> None:
    admission = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return
    superseded = dict(admission)
    superseded["admission_status"] = "superseded"
    superseded["updated_at"] = updated_at
    superseded["superseded_at"] = updated_at
    superseded["superseded_reason"] = "task_graph_replaced"
    superseded["superseded_by_graph_version"] = graph_version
    superseded["superseded_by_graph_fingerprint"] = graph_fingerprint
    metadata[MISSION_RUNTIME_ADMISSION_METADATA_KEY] = superseded


def _supersede_runtime_admission_for_materialization(
    *,
    metadata: dict[str, Any],
    materialization_version: int,
    updated_at: str,
) -> None:
    admission = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return
    superseded = dict(admission)
    superseded["admission_status"] = "superseded"
    superseded["updated_at"] = updated_at
    superseded["superseded_at"] = updated_at
    superseded["superseded_reason"] = "graph_materialization_replaced"
    superseded["superseded_by_materialization_version"] = materialization_version
    metadata[MISSION_RUNTIME_ADMISSION_METADATA_KEY] = superseded


def _runtime_admission_to_read(mission: Mission) -> RuntimeAdmissionRead:
    return RuntimeAdmissionRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        runtime_admission=mission.metadata_json.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY, {}),
        updated_at=mission.updated_at.isoformat(),
    )


def _cancel_superseded_materialized_planned_tasks(
    *, metadata: dict[str, Any], task_repo: ExecutionTaskRepository, tenant_id: str, mission_id: UUID
) -> list[str]:
    """Cancel planned ExecutionTask rows referenced by active runtime task materialization metadata."""
    task_materialization = metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
    if not isinstance(task_materialization, dict):
        return []
    raw_task_ids = task_materialization.get("created_execution_task_ids")
    if not isinstance(raw_task_ids, list):
        return []
    task_ids: list[UUID] = []
    for raw_task_id in raw_task_ids:
        try:
            task_ids.append(UUID(str(raw_task_id)))
        except ValueError:
            continue
    cancelled_tasks = task_repo.cancel_planned_by_ids_for_mission(
        tenant_id=tenant_id, mission_id=mission_id, task_ids=task_ids
    )
    return [str(task.id) for task in cancelled_tasks]


def _mission_to_read(mission: Mission) -> MissionRead:
    try:
        deliverable_runtime_state = build_deliverable_runtime_state_read(mission.metadata_json)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="mission deliverable runtime state is invalid") from exc
    return MissionRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        objective=mission.objective,
        status=mission.status,
        compliance_category=mission.compliance_category,
        jurisdiction=mission.jurisdiction,
        intake=mission.metadata_json.get(MISSION_INTAKE_METADATA_KEY, {}),
        deliverable_runtime_state=deliverable_runtime_state,
        created_at=mission.created_at.isoformat(),
        updated_at=mission.updated_at.isoformat(),
    )


def _mission_to_list_item(mission: Mission) -> MissionListItem:
    intake = mission.metadata_json.get(MISSION_INTAKE_METADATA_KEY, {})
    scope_limits = intake.get("scope_limits") if isinstance(intake, dict) else []
    allowed_actions = intake.get("allowed_actions") if isinstance(intake, dict) else []
    return MissionListItem(
        mission_id=mission.id,
        objective=mission.objective,
        status=mission.status,
        scope_limits=[str(item) for item in scope_limits] if isinstance(scope_limits, list) else [],
        allowed_actions=[str(item) for item in allowed_actions] if isinstance(allowed_actions, list) else [],
        created_at=mission.created_at.isoformat(),
        updated_at=mission.updated_at.isoformat(),
    )


def _mission_plan_to_read(mission: Mission) -> MissionPlanRead:
    legacy_plan = mission.metadata_json.get(MISSION_PLAN_METADATA_KEY, {})
    return MissionPlanRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        plan=legacy_plan,
        metadata=legacy_plan,
        updated_at=mission.updated_at.isoformat(),
    )


def _durable_mission_plan_to_read(plan: MissionPlan) -> MissionPlanRead:
    try:
        normalized_metadata = normalize_mission_plan_contract_metadata(plan.metadata_json)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    plan_payload = normalized_metadata.get("legacy_v1", normalized_metadata)
    return MissionPlanRead(
        plan_id=plan.id,
        mission_id=plan.mission_id,
        tenant_id=plan.tenant_id,
        status=plan.status,
        metadata=normalized_metadata,
        plan=plan_payload,
        created_at=plan.created_at.isoformat(),
        updated_at=plan.updated_at.isoformat(),
    )


def _mission_task_graph_to_read(mission: Mission) -> MissionTaskGraphRead:
    metadata = mission.metadata_json or {}
    task_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY)
    if not isinstance(task_graph, dict):
        raise HTTPException(status_code=409, detail="mission task graph metadata must be an object")
    try:
        normalized = normalize_mission_task_graph_contract_metadata(
            task_graph,
            allow_legacy_v1=mission_task_graph_allows_legacy_v1(metadata),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return MissionTaskGraphRead.model_validate(normalized)


def _graph_materialization_to_read(mission: Mission) -> GraphMaterializationRead:
    return GraphMaterializationRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        materialization=mission.metadata_json.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY, {}),
        updated_at=mission.updated_at.isoformat(),
    )


def _timeline_timestamp_or_mission_updated(*, value: Any, mission_updated_at_iso: str) -> str:
    """Return a valid ISO timestamp string or mission updated-at fallback."""
    if not isinstance(value, str):
        return mission_updated_at_iso
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return mission_updated_at_iso
    return value


def _timeline_sort_key(event: MissionTimelineEvent) -> tuple[datetime, str, str, str]:
    """Produce a deterministic sort key using parsed timestamp when possible."""
    try:
        parsed = datetime.fromisoformat(event.timestamp)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
    except ValueError:
        parsed = datetime.min.replace(tzinfo=UTC)
    return (parsed, event.timestamp, event.event_type, event.stage)


def _mission_timeline_to_read(
    *,
    mission: Mission,
    tasks: list[ExecutionTask],
    durable_plan: MissionPlan | None = None,
) -> MissionTimelineRead:
    mission_updated_at_iso = mission.updated_at.isoformat()
    events: list[MissionTimelineEvent] = [
        MissionTimelineEvent(
            timestamp=mission.created_at.isoformat(),
            event_type="mission_created",
            stage="mission_intake",
            source="mission",
            details={"status": mission.status},
        ),
        MissionTimelineEvent(
            timestamp=mission.updated_at.isoformat(),
            event_type="mission_updated",
            stage="mission_lifecycle",
            source="mission",
            details={"status": mission.status},
        ),
    ]

    if isinstance(durable_plan, MissionPlan):
        legacy_plan = (
            durable_plan.metadata_json.get("legacy_v1") if isinstance(durable_plan.metadata_json, dict) else None
        )
        plan_status = (
            legacy_plan.get("planning_status")
            if isinstance(legacy_plan, dict) and isinstance(legacy_plan.get("planning_status"), str)
            else durable_plan.status
        )
        events.append(
            MissionTimelineEvent(
                timestamp=durable_plan.updated_at.isoformat(),
                event_type="mission_plan_recorded",
                stage="mission_plan",
                source="mission_plan",
                details={"status": plan_status, "plan_id": str(durable_plan.id)},
            )
        )

    metadata = mission.metadata_json or {}
    metadata_stage_map = {
        MISSION_PLAN_METADATA_KEY: "mission_plan",
        MISSION_TASK_GRAPH_METADATA_KEY: "task_graph",
        MISSION_GRAPH_MATERIALIZATION_METADATA_KEY: "graph_materialization",
        MISSION_RUNTIME_ADMISSION_METADATA_KEY: "runtime_admission",
        MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY: "runtime_task_materialization",
        MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY: "runtime_queue_admission",
        MISSION_WORKER_CLAIM_ADMISSION_METADATA_KEY: "worker_claim_admission",
        MISSION_WORKER_START_ADMISSION_METADATA_KEY: "worker_start_admission",
        MISSION_WORKER_RUN_ADMISSION_METADATA_KEY: "worker_run_admission",
    }
    for key, stage in metadata_stage_map.items():
        if key == MISSION_PLAN_METADATA_KEY and isinstance(durable_plan, MissionPlan):
            continue
        value = metadata.get(key)
        if not isinstance(value, dict):
            continue
        updated_at = _timeline_timestamp_or_mission_updated(
            value=value.get("updated_at"), mission_updated_at_iso=mission_updated_at_iso
        )
        status = (
            value.get("admission_status")
            or value.get("materialization_status")
            or value.get("run_admission_status")
            or value.get("claim_admission_status")
            or value.get("start_admission_status")
            or value.get("planning_status")
            or value.get("graph_status")
            or "recorded"
        )
        events.append(
            MissionTimelineEvent(
                timestamp=updated_at,
                event_type=f"{stage}_recorded",
                stage=stage,
                source="mission_metadata",
                details={"status": status},
            )
        )

    for task in tasks:
        events.append(
            MissionTimelineEvent(
                timestamp=task.created_at.isoformat(),
                event_type="execution_task_created",
                stage="runtime_task",
                source="execution_task",
                details={"task_id": str(task.id)},
            )
        )
        if task.updated_at != task.created_at:
            events.append(
                MissionTimelineEvent(
                    timestamp=task.updated_at.isoformat(),
                    event_type="execution_task_updated",
                    stage="runtime_task",
                    source="execution_task",
                    details={"task_id": str(task.id), "status": task.status},
                )
            )

    events.sort(key=_timeline_sort_key)
    return MissionTimelineRead(mission_id=mission.id, tenant_id=mission.tenant_id, events=events)


def _mission_lifecycle_to_read(
    *,
    mission: Mission,
    durable_plan: MissionPlan | None,
    evidence_records: list[Any],
    outcome_reviews: list[Any],
    retrieval_contracts: list[Any],
) -> MissionLifecycleRead:
    metadata = mission.metadata_json or {}
    intake = metadata.get(MISSION_INTAKE_METADATA_KEY)
    legacy_plan = metadata.get(MISSION_PLAN_METADATA_KEY)
    plan: dict[str, Any] | None = None
    if durable_plan is not None:
        try:
            normalized_plan = normalize_mission_plan_contract_metadata(durable_plan.metadata_json)
            plan = normalized_plan.get("legacy_v1", normalized_plan)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    elif isinstance(legacy_plan, dict):
        plan = legacy_plan
    task_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY)
    normalized_task_graph: dict[str, Any] | None = None
    if task_graph is not None:
        try:
            normalized_task_graph = normalize_mission_task_graph_contract_metadata(
                task_graph,
                allow_legacy_v1=mission_task_graph_allows_legacy_v1(metadata),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    materialization = metadata.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    runtime_admission = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    has_memory_promotions = False

    completeness = MissionLifecycleCompleteness(
        has_intake=isinstance(intake, dict),
        has_plan=plan is not None,
        has_task_graph=normalized_task_graph is not None,
        has_materialization=isinstance(materialization, dict),
        has_runtime_admission=(
            isinstance(runtime_admission, dict) and runtime_admission.get("admission_status") == "admitted"
        ),
        has_evidence=bool(evidence_records),
        has_outcome_review=bool(outcome_reviews),
        has_memory_promotions=has_memory_promotions,
        has_retrieval_contracts=bool(retrieval_contracts),
    )
    # Runtime execution ladder only — these block "ready to run workers".
    missing_next_steps: list[str] = []
    if not completeness.has_plan:
        missing_next_steps.append("create_mission_plan")
    if not completeness.has_task_graph:
        missing_next_steps.append("create_task_graph")
    if not completeness.has_materialization:
        missing_next_steps.append("materialize_task_graph")
    if not completeness.has_runtime_admission:
        missing_next_steps.append("admit_graph_to_runtime")

    # Optional close-out — mission product after workers, not pipeline incompleteness.
    optional_closeout_steps: list[str] = []
    if not completeness.has_evidence:
        optional_closeout_steps.append("attach_evidence")
    if not completeness.has_outcome_review:
        optional_closeout_steps.append("create_outcome_review")
    if not completeness.has_memory_promotions:
        optional_closeout_steps.append("review_memory_promotion")
    if not completeness.has_retrieval_contracts:
        optional_closeout_steps.append("create_retrieval_contract")

    return MissionLifecycleRead(
        mission=MissionLifecycleMissionSummary(
            mission_id=mission.id,
            tenant_id=mission.tenant_id,
            objective=mission.objective,
            status=mission.status,
            compliance_category=mission.compliance_category,
            jurisdiction=mission.jurisdiction,
            created_at=mission.created_at.isoformat(),
            updated_at=mission.updated_at.isoformat(),
        ),
        intake=intake if isinstance(intake, dict) else None,
        plan=plan,
        task_graph=normalized_task_graph,
        materialization=materialization if isinstance(materialization, dict) else None,
        runtime_admission=runtime_admission if isinstance(runtime_admission, dict) else None,
        evidence=MissionLifecycleEvidenceSummary(
            count=len(evidence_records),
            records=[
                MissionLifecycleEvidenceItem(
                    evidence_id=record.id,
                    evidence_type=record.evidence_type,
                    evidence_source=record.evidence_source,
                    collection_status=record.collection_status,
                    confidence=record.confidence,
                    created_at=record.created_at.isoformat(),
                    updated_at=record.updated_at.isoformat(),
                )
                for record in evidence_records
            ],
        ),
        outcome_reviews=MissionLifecycleOutcomeReviewSummary(
            count=len(outcome_reviews),
            records=[
                MissionLifecycleOutcomeReviewItem(
                    review_id=review.id,
                    review_status=review.review_status,
                    review_decision=review.review_decision,
                    reviewer_type=review.reviewer_type,
                    confidence=review.confidence,
                    created_at=review.created_at.isoformat(),
                    updated_at=review.updated_at.isoformat(),
                )
                for review in outcome_reviews
            ],
        ),
        memory_promotions=MissionLifecycleMemoryPromotionSummary(count=0, records=[]),
        retrieval_contracts=MissionLifecycleRetrievalContractSummary(
            count=len(retrieval_contracts),
            records=[
                MissionLifecycleRetrievalContractItem(
                    retrieval_id=retrieval.id,
                    retrieval_strategy=retrieval.retrieval_strategy,
                    retrieval_status=retrieval.retrieval_status,
                    confidence=retrieval.confidence,
                    created_at=retrieval.created_at.isoformat(),
                    updated_at=retrieval.updated_at.isoformat(),
                )
                for retrieval in retrieval_contracts
            ],
        ),
        completeness=completeness,
        missing_next_steps=missing_next_steps,
        optional_closeout_steps=optional_closeout_steps,
    )


@router.post("", response_model=MissionRead, status_code=201)
def create_mission(
    body: MissionCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionRead:
    """Create a tenant-owned mission intake record without queueing runtime work."""
    require_route_permission(request=request, db=db, permission=Permission.MISSION_CREATE, tenant_id=tenant_id)
    if contains_composition_clarification(body.context):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INTAKE_QUALITY",
                "message": "Planner clarification text cannot be submitted as a mission objective; restate the intended mission.",
            },
        )
    if get_settings().mission_intake_quality_mode == "enforce":
        try:
            validate_mission_intake_prompt(
                objective=body.objective,
                success_criteria=[criterion.model_dump() for criterion in body.success_criteria],
                constraints=[constraint.model_dump() for constraint in body.constraints],
                scope_limits=body.scope_limits,
                allowed_actions=body.allowed_actions,
                operator_notes=body.operator_notes,
                allow_legacy_v1=body.allow_legacy_v1,
            )
        except MissionIntakeQualityDeniedError as exc:
            raise HTTPException(status_code=422, detail=exc.to_detail()) from exc

    quota = QuotaEnforcementService(db)
    budget_limits = body.budget_limits.model_dump(exclude_none=True) if body.budget_limits else None
    try:
        quota.enforce_mission_budget_gate(tenant_id, budget_limits)
        quota.check_and_record_mission_creation(tenant_id)
    except BudgetGateDeniedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except QuotaExceededError as exc:
        raise _quota_exceeded_response(exc) from exc

    intake_metadata = build_mission_intake_metadata(
        success_criteria=[criterion.model_dump() for criterion in body.success_criteria],
        constraints=[constraint.model_dump() for constraint in body.constraints],
        operator_notes=body.operator_notes,
        context=body.context,
        priority=body.priority,
        approval_required=body.approval_required,
        approval_expectations=body.approval_expectations,
        budget_limits=budget_limits,
        scope_limits=body.scope_limits,
        allowed_actions=body.allowed_actions,
        allowed_tools=body.allowed_tools,
        allow_legacy_v1=body.allow_legacy_v1,
    )
    mission = MissionRepository(db).add(
        Mission(
            tenant_id=str(tenant_id),
            objective=body.objective,
            status=MissionState.PLANNED.value,
            compliance_category=body.compliance_category,
            jurisdiction=body.jurisdiction,
            metadata_json=intake_metadata,
        )
    )
    return _mission_to_read(mission)


@router.get("", response_model=MissionListResponse)
def list_missions(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> MissionListResponse:
    """List tenant-owned missions newest-first for product navigation."""
    repository = MissionRepository(db)
    missions = repository.list_by_tenant(str(tenant_id), limit=limit)
    items = [_mission_to_list_item(mission) for mission in missions]
    return MissionListResponse(
        missions=items,
        count=len(items),
        total_count=repository.count_by_tenant(str(tenant_id)),
        completed_count=repository.count_completed_by_tenant(str(tenant_id)),
    )


@router.get("/{mission_id}", response_model=MissionRead)
def read_mission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionRead:
    """Read one tenant-owned mission through a tenant-scoped repository query."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    return _mission_to_read(mission)


@router.get("/{mission_id}/lifecycle", response_model=MissionLifecycleRead)
def read_mission_lifecycle(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionLifecycleRead:
    """Read one mission as a tenant-scoped product lifecycle without runtime side effects."""
    tenant_scope = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    durable_plan = MissionPlanRepository(db).get_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    evidence_records = EvidenceRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    outcome_reviews = OutcomeReviewRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    retrieval_contracts = RetrievalContractRepository(db).list_for_mission(
        mission_id=mission_id, tenant_id=tenant_scope
    )
    return _mission_lifecycle_to_read(
        mission=mission,
        durable_plan=durable_plan if isinstance(durable_plan, MissionPlan) else None,
        evidence_records=evidence_records,
        outcome_reviews=outcome_reviews,
        retrieval_contracts=retrieval_contracts,
    )


@router.get("/{mission_id}/timeline", response_model=MissionTimelineRead)
def read_mission_timeline(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionTimelineRead:
    """Read-only mission timeline across mission bridge and runtime surfaces."""
    tenant_scope = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    tasks = [
        task
        for task in ExecutionTaskRepository(db).list_for_mission(mission_id=mission_id)
        if task.tenant_id == tenant_scope
    ]
    durable_plan = MissionPlanRepository(db).get_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    return _mission_timeline_to_read(
        mission=mission,
        tasks=tasks,
        durable_plan=durable_plan if isinstance(durable_plan, MissionPlan) else None,
    )


@router.post("/{mission_id}/plan", response_model=MissionPlanRead)
def create_mission_plan(
    mission_id: UUID,
    body: MissionPlanCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionPlanRead:
    """Create or return an active tenant-scoped mission plan without runtime side effects."""
    require_route_permission(request=request, db=db, permission=Permission.MISSION_MANAGE, tenant_id=tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    metadata = build_mission_plan_contract_metadata(
        objectives=body.objectives,
        constraints=body.constraints,
        assumptions=body.assumptions,
        acceptance_criteria=body.acceptance_criteria,
        planned_steps=[step.model_dump() for step in body.planned_steps],
        risk_notes=body.risk_notes,
    )
    plan = MissionPlanRepository(db).create_or_get_active_for_mission(
        mission=mission,
        status=MissionPlanStatus.DRAFT.value,
        metadata_json=metadata,
    )
    return _durable_mission_plan_to_read(plan)


@router.put("/{mission_id}/plan", response_model=MissionPlanRead)
def upsert_mission_plan(
    mission_id: UUID,
    body: MissionPlanWrite,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionPlanRead:
    """Create or replace a tenant-scoped mission plan without queueing work."""
    require_route_permission(request=request, db=db, permission=Permission.MISSION_MANAGE, tenant_id=tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    plan_repo = MissionPlanRepository(db)
    metadata = build_mission_plan_contract_metadata_from_legacy_write(
        planning_status=body.planning_status,
        phases=[phase.model_dump() for phase in body.phases],
        planning_notes=body.planning_notes,
        desired_outputs=[output.model_dump() for output in body.desired_outputs],
        capability_requirements=[requirement.model_dump() for requirement in body.capability_requirements],
        execution_strategy_hints=body.execution_strategy_hints,
        approval_gates=[gate.model_dump() for gate in body.approval_gates],
        operator_overrides=body.operator_overrides,
        estimated_scope=body.estimated_scope.model_dump(exclude_none=True),
        risk_annotations=[risk.model_dump() for risk in body.risk_annotations],
    )
    target_status = legacy_mission_plan_status_from_planning_status(body.planning_status)
    durable_plan = plan_repo.get_for_mission(mission_id=mission_id, tenant_id=str(tenant_id))
    if isinstance(durable_plan, MissionPlan):
        if durable_plan.status not in {MissionPlanStatus.DRAFT.value, MissionPlanStatus.READY.value}:
            raise HTTPException(status_code=409, detail="mission plan is not active and cannot be replaced")
        try:
            plan = plan_repo.replace_active_plan(
                plan=durable_plan,
                metadata_json=metadata,
                status=target_status,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _durable_mission_plan_to_read(plan)

    if target_status != MissionPlanStatus.DRAFT.value:
        try:
            validate_mission_plan_status_transition(MissionPlanStatus.DRAFT.value, target_status)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    plan = plan_repo.create_or_get_active_for_mission(
        mission=mission,
        status=target_status,
        metadata_json=metadata,
    )
    return _durable_mission_plan_to_read(plan)


@router.get("/{mission_id}/plan", response_model=MissionPlanRead)
def read_mission_plan(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionPlanRead:
    """Read a tenant-scoped durable mission plan without creating one as a side effect."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    durable_plan = MissionPlanRepository(db).get_for_mission(mission_id=mission_id, tenant_id=str(tenant_id))
    if isinstance(durable_plan, MissionPlan):
        return _durable_mission_plan_to_read(durable_plan)

    if MISSION_PLAN_METADATA_KEY not in (mission.metadata_json or {}):
        raise HTTPException(status_code=404, detail="mission plan not found")
    return _mission_plan_to_read(mission)


def _write_mission_task_graph(
    *,
    mission_id: UUID,
    body: dict[str, Any],
    tenant_id: _uuid.UUID,
    db: Session,
) -> MissionTaskGraphRead:
    """Create or fully replace a tenant-scoped task graph contract with no runtime side effects."""
    repo = MissionRepository(db)
    mission = repo.get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    metadata = dict(mission.metadata_json or {})
    allow_legacy_v1 = mission_task_graph_allows_legacy_v1(metadata)
    try:
        normalized_graph = normalize_mission_task_graph_contract_metadata(body, allow_legacy_v1=allow_legacy_v1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Strip browser-forged side_effect_authorization before persistence.
    # Server remints SE auth at ExecutionTask materialization when required.
    from backend.services.tools.schemas import is_client_forged_side_effect_approver

    sanitized_nodes: list[Any] = []
    for node in normalized_graph.get("nodes") or []:
        if not isinstance(node, dict):
            sanitized_nodes.append(node)
            continue
        node_copy = dict(node)
        input_contract = node_copy.get("input_contract")
        if isinstance(input_contract, dict):
            input_contract = dict(input_contract)
            constraints = input_contract.get("execution_constraints")
            if isinstance(constraints, dict):
                constraints = dict(constraints)
                raw_auth = constraints.get("side_effect_authorization")
                if isinstance(raw_auth, dict) and is_client_forged_side_effect_approver(
                    str(raw_auth.get("approved_by") or "")
                ):
                    constraints.pop("side_effect_authorization", None)
                    if constraints:
                        input_contract["execution_constraints"] = constraints
                    else:
                        input_contract.pop("execution_constraints", None)
            node_copy["input_contract"] = input_contract
        sanitized_nodes.append(node_copy)
    normalized_graph = {**normalized_graph, "nodes": sanitized_nodes}

    existing_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY)
    if existing_graph is not None:
        try:
            normalized_existing_graph = normalize_mission_task_graph_contract_metadata(
                existing_graph, allow_legacy_v1=allow_legacy_v1
            )
        except ValueError:
            normalized_existing_graph = None
        if (
            normalized_existing_graph is not None
            and _task_graph_has_identity(normalized_existing_graph)
            and _task_graph_contract_content(normalized_existing_graph)
            == _task_graph_contract_content(normalized_graph)
        ):
            return MissionTaskGraphRead.model_validate(normalized_existing_graph)

    graph_version = _next_task_graph_version(existing_graph)
    graph_metadata = _task_graph_with_identity(
        mission_id=mission_id,
        normalized_graph=build_mission_task_graph_contract_metadata(
            nodes=normalized_graph["nodes"],
            edges=normalized_graph["edges"],
            metadata=normalized_graph["metadata"],
        ),
        graph_version=graph_version,
    )
    metadata[MISSION_TASK_GRAPH_METADATA_KEY] = graph_metadata
    graph_fingerprint = graph_metadata["graph_fingerprint"]
    updated_at = datetime.now(UTC).isoformat()
    _supersede_graph_materialization(
        metadata=metadata, graph_version=graph_version, graph_fingerprint=graph_fingerprint, updated_at=updated_at
    )
    _supersede_runtime_admission(
        metadata=metadata, graph_version=graph_version, graph_fingerprint=graph_fingerprint, updated_at=updated_at
    )
    cancelled_task_ids: list[str] = []
    if isinstance(metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY), dict):
        cancelled_task_ids = _cancel_superseded_materialized_planned_tasks(
            metadata=metadata,
            task_repo=ExecutionTaskRepository(db),
            tenant_id=str(tenant_id),
            mission_id=mission_id,
        )
    supersede_runtime_task_materialization(
        metadata=metadata,
        reason="task_graph_replaced",
        updated_at=updated_at,
        supersession={
            "superseded_by_graph_version": graph_version,
            "superseded_by_graph_fingerprint": graph_fingerprint,
            "cancelled_execution_task_ids": cancelled_task_ids,
        },
    )
    mission = repo.update_metadata(mission=mission, metadata_json=metadata)
    return _mission_task_graph_to_read(mission)


@router.post("/{mission_id}/task-graph", response_model=MissionTaskGraphRead)
def create_mission_task_graph(
    mission_id: UUID,
    body: dict[str, Any],
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionTaskGraphRead:
    """Create or replace a tenant-scoped task graph contract without queueing work."""
    require_route_permission(request=request, db=db, permission=Permission.MISSION_MANAGE, tenant_id=tenant_id)
    return _write_mission_task_graph(mission_id=mission_id, body=body, tenant_id=tenant_id, db=db)


@router.put("/{mission_id}/task-graph", response_model=MissionTaskGraphRead)
def upsert_mission_task_graph(
    mission_id: UUID,
    body: dict[str, Any],
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionTaskGraphRead:
    """Create or fully replace a tenant-scoped task graph contract without queueing work."""
    require_route_permission(request=request, db=db, permission=Permission.MISSION_MANAGE, tenant_id=tenant_id)
    return _write_mission_task_graph(mission_id=mission_id, body=body, tenant_id=tenant_id, db=db)


@router.get("/{mission_id}/task-graph", response_model=MissionTaskGraphRead)
def read_mission_task_graph(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionTaskGraphRead:
    """Read a tenant-scoped task graph contract if one has been persisted."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    if MISSION_TASK_GRAPH_METADATA_KEY not in (mission.metadata_json or {}):
        raise HTTPException(status_code=404, detail="mission task graph not found")
    return _mission_task_graph_to_read(mission)


@router.post("/{mission_id}/compile", response_model=MissionCompileResponse)
def compile_mission(
    mission_id: UUID,
    request: Request,
    body: MissionCompileRequest | None = None,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionCompileResponse:
    """Compile a server-owned plan/graph for an existing mission.

    Replaces client graph compilers (missionBridge.buildTaskGraphPayload). Does not
    queue work, claim leases, or invoke tools. When persist=true and compile is ready,
    writes task graph + refreshes intake allowed_actions and supersedes stale admission.
    """
    require_route_permission(request=request, db=db, permission=Permission.MISSION_MANAGE, tenant_id=tenant_id)
    from backend.services.mission_composition.service import (
        MissionCompositionError,
        MissionCompositionService,
    )

    payload = body or MissionCompileRequest()
    actor = request.headers.get("x-ajenda-actor") or request.headers.get("x-user-id") or None
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        for attr in ("subject_id", "subject", "sub"):
            subject = getattr(principal, attr, None)
            if isinstance(subject, str) and subject.strip():
                actor = subject.strip()
                break

    service = MissionCompositionService(db)
    try:
        result = service.compile_for_mission(
            tenant_id=str(tenant_id),
            mission_id=mission_id,
            instruction=payload.instruction,
            persist=payload.persist,
            source=payload.source,
            actor_id=actor,
        )
    except MissionCompositionError as exc:
        status = 400
        if exc.code == "MISSION_NOT_FOUND":
            status = 404
        elif exc.code in {"NO_RUNTIME_ACTIONS", "PROPOSAL_NOT_READY", "INSTRUCTION_REQUIRED"}:
            status = 422
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from exc
    return MissionCompileResponse.model_validate(result)


@router.post("/{mission_id}/launch", response_model=MissionLaunchResponse)
def launch_mission(
    mission_id: UUID,
    request: Request,
    body: dict[str, Any] | None = None,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> MissionLaunchResponse:
    """Explicitly orchestrate compile, admission, task materialization, and queue admission.

    Each stage remains independently callable for review/recovery. This endpoint only
    composes those existing authorities and never dispatches workers directly.
    """
    require_route_permission(request=request, db=db, permission=Permission.MISSION_MANAGE, tenant_id=tenant_id)
    require_route_permission(request=request, db=db, permission=Permission.RUNTIME_OPERATE, tenant_id=tenant_id)
    require_route_permission(request=request, db=db, permission=Permission.EXECUTION_QUEUE, tenant_id=tenant_id)

    from backend.services.mission_composition.service import MissionCompositionService

    payload = body or {}
    idempotency_key = request.headers.get("Idempotency-Key") or payload.get("idempotency_key")
    if idempotency_key is not None:
        idempotency_key = str(idempotency_key).strip() or None
    compile_result = MissionCompositionService(db).compile_for_mission(
        tenant_id=str(tenant_id),
        mission_id=mission_id,
        instruction=payload.get("instruction") if isinstance(payload.get("instruction"), str) else None,
        persist=True,
        source="mission_launch",
        actor_id=request.headers.get("x-ajenda-actor"),
    )
    if compile_result.get("compile_status") != "ready":
        raise HTTPException(status_code=422, detail={"code": "COMPILE_NOT_READY", "compile": compile_result})

    # Compile persists the server-owned graph materialization. Runtime admission
    # provisions bridge authority and records the graph-to-runtime receipt.
    admit_mission_graph_to_runtime(
        mission_id=mission_id,
        body=RuntimeAdmissionWrite(),
        request=request,
        tenant_id=tenant_id,
        db=db,
    )
    materialized = materialize_mission_runtime_tasks(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
    )
    admission = _admit_mission_runtime_queue(mission_id=mission_id, tenant_id=tenant_id, db=db, queue=queue)
    blockers_raw = admission.get("blockers")
    queued_raw = admission.get("queued_task_ids")
    pending_raw = admission.get("pending_review_task_ids")
    blockers = list(blockers_raw) if isinstance(blockers_raw, list) else []
    queued_task_ids = [str(item) for item in queued_raw] if isinstance(queued_raw, list) else []
    pending_review_task_ids = [str(item) for item in pending_raw] if isinstance(pending_raw, list) else []
    return MissionLaunchResponse(
        mission_id=mission_id,
        compile_status=str(compile_result.get("compile_status") or "unknown"),
        graph_materialized=True,
        runtime_admitted=True,
        runtime_tasks_materialized=len(getattr(materialized, "created_execution_task_ids", []) or []),
        queued_task_ids=queued_task_ids,
        pending_review_task_ids=pending_review_task_ids,
        blockers=blockers,
        idempotency_key=idempotency_key,
    )


@router.post("/{mission_id}/materialize-graph", response_model=GraphMaterializationRead)
def materialize_mission_graph(
    mission_id: UUID,
    body: dict[str, Any] | None,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> GraphMaterializationRead:
    """Persist planner-to-graph materialization metadata without runtime work."""
    require_route_permission(request=request, db=db, permission=Permission.MISSION_MANAGE, tenant_id=tenant_id)
    tenant_id_str = str(tenant_id)
    repo = MissionRepository(db)
    mission = repo.get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    metadata = dict(mission.metadata_json or {})
    task_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY)
    if not isinstance(task_graph, dict):
        raise HTTPException(status_code=400, detail="mission task graph is required before materialization")

    graph_nodes = task_graph.get("nodes")
    if not isinstance(graph_nodes, list):
        raise HTTPException(status_code=400, detail="mission task graph nodes are required before materialization")
    node_keys = {node.get("key") for node in graph_nodes if isinstance(node, dict)}
    if len(node_keys) != len(graph_nodes) or any(not isinstance(key, str) or not key for key in node_keys):
        raise HTTPException(status_code=400, detail="mission task graph nodes must have valid keys")

    # The UI may request server-owned materialization with an empty body.  Build
    # provenance from the persisted graph rather than requiring the client to
    # manufacture authority metadata.
    if not body:
        graph_metadata = task_graph.get("metadata")
        if not isinstance(graph_metadata, dict) or graph_metadata.get("generated_by") != "mission_composition_engine":
            raise HTTPException(
                status_code=409,
                detail="empty materialization requests require a server-composed task graph",
            )
        proposal_id = graph_metadata.get("proposal_id")
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            raise HTTPException(
                status_code=409,
                detail="server-composed task graph is missing proposal provenance",
            )
        now = datetime.now(UTC).isoformat()
        graph_fingerprint = str(task_graph.get("graph_fingerprint") or "")
        body = {
            "materialization_status": "validated",
            "materialization_source": "mission_composition_confirmed",
            "materialization_source_version": "1",
            "planner_provenance": {
                "planner_type": "mission_composition_engine",
                "planner_id": "mission_composition_engine",
                "planning_run_id": proposal_id,
                "plan_schema_version": 1,
            },
            "graph_validation_result": {
                "validation_status": "valid",
                "summary": "Server validated persisted composition graph structure.",
                "validated_at": now,
                "checks": [
                    {"name": "node_keys", "status": "passed", "details": f"nodes={len(graph_nodes)}"},
                    {"name": "server_owned", "status": "passed", "details": "metadata generated by API"},
                ],
            },
            "graph_generation_metadata": {
                "generator": "mission_composition_engine",
                "generation_mode": "deterministic",
                "generated_at": now,
                "compiler_version": "1",
                "source_plan_version": "1",
                "deterministic_inputs": {"graph_fingerprint": graph_fingerprint},
            },
            "deterministic_compilation_metadata": {
                "compiler_name": "mission_composition_engine",
                "compiler_version": "1",
                "compilation_boundary": "confirmed_composition_to_materialized_graph",
                "input_fingerprint": graph_fingerprint or None,
                "output_fingerprint": graph_fingerprint or None,
                "deterministic": True,
            },
        }
    try:
        body_model = GraphMaterializationWrite.model_validate(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    capability_repo = CapabilityRepository(db)
    for selection in body_model.capability_selection_provenance:
        if selection.node_key not in node_keys:
            raise HTTPException(
                status_code=400, detail=f"capability selection references missing node: {selection.node_key}"
            )
        if selection.capability_id is not None:
            capability = capability_repo.get_visible_for_tenant(
                capability_id=selection.capability_id, tenant_id=tenant_id_str
            )
            if capability is None:
                raise HTTPException(
                    status_code=400, detail=f"capability not found for tenant: {selection.capability_id}"
                )

    previous = metadata.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    previous_version = previous.get("materialization_version", 0) if isinstance(previous, dict) else 0
    now = datetime.now(UTC).isoformat()

    # Trust boundary: client may not self-certify graph validation as "valid".
    # Accept structural node-key checks server-side; never store client-forged validity.
    materialization_status = body_model.materialization_status
    validation = body_model.graph_validation_result.model_dump(mode="json", exclude_none=True)
    client_sources = {"mission_dispatch_ui", "mission-dispatch-ui", "dispatch-ui-v1"}
    source = body_model.materialization_source.strip().lower()
    if source in client_sources or source.startswith("mission_dispatch") or source.startswith("mission-dispatch"):
        if materialization_status == "validated":
            materialization_status = "draft"
        if validation.get("validation_status") == "valid":
            validation = {
                "validation_status": "not_run",
                "summary": (
                    "Client claimed validation was discarded; "
                    "server structural node-key checks ran at materialize-graph."
                ),
                "checks": [
                    {
                        "name": "node_keys",
                        "status": "passed",
                        "details": "Server verified node keys are unique non-empty strings.",
                    }
                ],
            }

    materialization_metadata = build_graph_materialization_metadata(
        mission_id=str(mission_id),
        materialization_status=materialization_status,
        materialization_source=body_model.materialization_source,
        materialization_source_version=body_model.materialization_source_version,
        materialization_version=previous_version + 1,
        planner_provenance=body_model.planner_provenance.model_dump(mode="json", exclude_none=True),
        capability_selection_provenance=[
            selection.model_dump(mode="json", exclude_none=True)
            for selection in body_model.capability_selection_provenance
        ],
        graph_validation_result=validation,
        operator_review=body_model.operator_review.model_dump(mode="json", exclude_none=True),
        graph_generation_metadata=body_model.graph_generation_metadata.model_dump(mode="json", exclude_none=True),
        deterministic_compilation_metadata=body_model.deterministic_compilation_metadata.model_dump(
            mode="json", exclude_none=True
        ),
        generation_notes=body_model.generation_notes,
        materialized_at=previous.get("materialized_at", now) if isinstance(previous, dict) else now,
        updated_at=now,
        graph_reference={
            "metadata_key": MISSION_TASK_GRAPH_METADATA_KEY,
            "schema_version": task_graph.get("schema_version"),
            "graph_status": task_graph.get("graph_status"),
            "graph_version": task_graph.get("graph_version"),
            "graph_fingerprint": task_graph.get("graph_fingerprint") or _fingerprint_existing_task_graph(task_graph),
            "node_count": len(graph_nodes),
            "edge_count": len(task_graph.get("edges", [])) if isinstance(task_graph.get("edges", []), list) else 0,
        },
    )
    if isinstance(metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY), dict):
        _supersede_runtime_admission_for_materialization(
            metadata=metadata,
            materialization_version=previous_version + 1,
            updated_at=now,
        )
    cancelled_task_ids: list[str] = []
    if isinstance(metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY), dict):
        cancelled_task_ids = _cancel_superseded_materialized_planned_tasks(
            metadata=metadata,
            task_repo=ExecutionTaskRepository(db),
            tenant_id=tenant_id_str,
            mission_id=mission_id,
        )
    supersede_runtime_task_materialization(
        metadata=metadata,
        reason="graph_materialization_replaced",
        updated_at=now,
        supersession={
            "superseded_by_materialization_version": previous_version + 1,
            "cancelled_execution_task_ids": cancelled_task_ids,
        },
    )
    metadata.update(materialization_metadata)
    mission = repo.update_metadata(mission=mission, metadata_json=metadata)
    return _graph_materialization_to_read(mission)


@router.get("/{mission_id}/materialization", response_model=GraphMaterializationRead)
def read_mission_graph_materialization(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> GraphMaterializationRead:
    """Read tenant-scoped planner-to-graph materialization metadata."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    if MISSION_GRAPH_MATERIALIZATION_METADATA_KEY not in (mission.metadata_json or {}):
        raise HTTPException(status_code=404, detail="mission graph materialization not found")
    return _graph_materialization_to_read(mission)


@router.post("/{mission_id}/runtime-admission", response_model=RuntimeAdmissionRead)
def admit_mission_graph_to_runtime(
    mission_id: UUID,
    body: RuntimeAdmissionWrite,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeAdmissionRead:
    """Persist graph-to-runtime admission metadata without queueing or dispatch.

    Server owns admission identity and can derive selected nodes from the compiled graph.
    """
    require_route_permission(request=request, db=db, permission=Permission.RUNTIME_OPERATE, tenant_id=tenant_id)
    tenant_id_str = str(tenant_id)
    repo = MissionRepository(db)
    mission = repo.get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    metadata = dict(mission.metadata_json or {})
    task_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY)
    if not isinstance(task_graph, dict):
        raise HTTPException(status_code=400, detail="mission task graph is required before runtime admission")

    materialization = metadata.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    if not isinstance(materialization, dict):
        raise HTTPException(
            status_code=400, detail="mission graph materialization is required before runtime admission"
        )

    if materialization.get("materialization_status") == "superseded":
        raise HTTPException(status_code=400, detail="superseded graph materialization cannot be admitted")

    graph_nodes = task_graph.get("nodes")
    if not isinstance(graph_nodes, list) or not all(isinstance(node, dict) for node in graph_nodes):
        raise HTTPException(status_code=400, detail="mission task graph nodes are required before runtime admission")
    nodes_by_key = {node.get("key"): node for node in graph_nodes if isinstance(node.get("key"), str)}
    if len(nodes_by_key) != len(graph_nodes):
        raise HTTPException(status_code=400, detail="mission task graph nodes must have valid keys")

    graph_version = task_graph.get("graph_version")
    graph_fingerprint = task_graph.get("graph_fingerprint") or _fingerprint_existing_task_graph(task_graph)
    graph_reference = materialization.get("graph_reference")
    if not isinstance(graph_reference, dict):
        raise HTTPException(
            status_code=400, detail="materialization graph reference is required before runtime admission"
        )
    if (
        graph_reference.get("graph_version") != graph_version
        or graph_reference.get("graph_fingerprint") != graph_fingerprint
    ):
        raise HTTPException(status_code=400, detail="materialization graph reference does not match current task graph")

    outcome_reviews = OutcomeReviewRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_id_str)
    rejected_reviews = [
        review
        for review in outcome_reviews
        if review.review_status == "rejected" or review.review_decision == "rejected"
    ]
    if rejected_reviews:
        raise HTTPException(status_code=400, detail="rejected outcome review blocks runtime admission")

    intake_for_graft = metadata.get(MISSION_INTAKE_METADATA_KEY)
    intake_context = intake_for_graft.get("context") if isinstance(intake_for_graft, dict) else None
    composition_for_graft = intake_context.get("composition") if isinstance(intake_context, dict) else None
    compiled_instruction = (
        composition_for_graft.get("instruction")
        if isinstance(composition_for_graft, dict) and isinstance(composition_for_graft.get("instruction"), str)
        else None
    )
    # Mission objective is the server-normalized instruction.  The stored
    # composition instruction preserves the raw operator text for provenance
    # and may still contain harmless Markdown quote prefixes; feeding that raw
    # copy to GRAFT would reject a mission that already compiled successfully.
    graft_instruction = (mission.objective or compiled_instruction or "").strip()
    graft_report = evaluate_admission_integrity(
        session=db,
        tenant_id=tenant_id_str,
        instruction=graft_instruction,
        task_graph=task_graph,
    )
    if graft_report["status"] != "clear":
        raise HTTPException(
            status_code=400,
            detail={"message": "GRAFT runtime admission blocked", "graft": graft_report},
        )

    admitted_by = _server_admitted_by(request=request, body_admitted_by=body.admitted_by)
    node_selections = list(body.selected_nodes)
    if not node_selections:
        if not body.auto_provision_authority:
            raise HTTPException(
                status_code=400,
                detail="selected_nodes required when auto_provision_authority is false",
            )
        provisioned = provision_bridge_runtime_authority(
            db=db,
            mission_id=mission_id,
            tenant_id=tenant_id,
            admitted_by=admitted_by,
        )
        # Graph may have been rewritten with capability ids; re-read mission metadata snapshot.
        mission = repo.get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str) or mission
        metadata = dict(mission.metadata_json or {})
        task_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY) or task_graph
        graph_nodes = task_graph.get("nodes") if isinstance(task_graph, dict) else graph_nodes
        if not isinstance(graph_nodes, list):
            raise HTTPException(
                status_code=400, detail="mission task graph nodes are required before runtime admission"
            )
        nodes_by_key = {
            node.get("key"): node for node in graph_nodes if isinstance(node, dict) and isinstance(node.get("key"), str)
        }
        authority_by_key = {
            item["node_key"]: item
            for item in provisioned.get("node_authorities", [])
            if isinstance(item, dict) and isinstance(item.get("node_key"), str)
        }
        for node_key, authority in authority_by_key.items():
            if node_key not in nodes_by_key:
                continue
            try:
                provisioned_capability_id = UUID(str(authority["capability_id"]))
                provisioned_adapter_id = UUID(str(authority["adapter_id"]))
            except (KeyError, ValueError, TypeError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"bridge authority missing capability/adapter for node: {node_key}",
                ) from exc
            node_selections.append(
                RuntimeAdmissionNodeSelection(
                    node_key=node_key,
                    runtime_task_type="tool.invoke",
                    capability_id=provisioned_capability_id,
                    adapter_id=provisioned_adapter_id,
                    operator_notes="Server-derived admission from compiled graph.",
                )
            )
        if not node_selections:
            raise HTTPException(
                status_code=400,
                detail="no runtime-admissible tool.invoke nodes found on compiled task graph",
            )

    capability_repo = CapabilityRepository(db)
    adapter_repo = CapabilityAdapterRepository(db)
    selections_by_node = {
        selection.get("node_key"): selection
        for selection in materialization.get("capability_selection_provenance", [])
        if isinstance(selection, dict) and isinstance(selection.get("node_key"), str)
    }

    validation_checks: list[dict[str, str]] = []
    selected_nodes: list[dict[str, Any]] = []
    for selection in node_selections:
        node = nodes_by_key.get(selection.node_key)
        if node is None:
            raise HTTPException(
                status_code=400, detail=f"runtime admission references missing node: {selection.node_key}"
            )

        runtime_task_type = selection.runtime_task_type or node.get("intended_task_type")
        if not isinstance(runtime_task_type, str) or not runtime_task_type.strip():
            raise HTTPException(
                status_code=400, detail=f"runtime admission node lacks runtime task type: {selection.node_key}"
            )
        runtime_task_type = runtime_task_type.strip()

        node_capability_refs = (
            node.get("capability_references") if isinstance(node.get("capability_references"), list) else []
        )
        materialized_selection = selections_by_node.get(selection.node_key)
        capability_id = selection.capability_id
        materialized_capability_id: UUID | None = None
        if isinstance(materialized_selection, dict):
            raw_materialized_capability_id = materialized_selection.get("capability_id")
            if isinstance(raw_materialized_capability_id, str):
                try:
                    materialized_capability_id = UUID(raw_materialized_capability_id)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"materialization capability_id is invalid for node: {selection.node_key}",
                    ) from exc

        if (
            capability_id is not None
            and materialized_capability_id is not None
            and capability_id != materialized_capability_id
        ):
            raise HTTPException(
                status_code=400,
                detail=f"runtime admission capability conflicts with materialization: {selection.node_key}",
            )

        if capability_id is None and materialized_capability_id is not None:
            capability_id = materialized_capability_id

        if capability_id is None:
            for capability_ref in node_capability_refs:
                if isinstance(capability_ref, dict) and isinstance(capability_ref.get("capability_id"), str):
                    try:
                        capability_id = UUID(capability_ref["capability_id"])
                    except ValueError as exc:
                        raise HTTPException(
                            status_code=400,
                            detail=f"task graph capability_id is invalid for node: {selection.node_key}",
                        ) from exc
                    break

        if capability_id is None and not node_capability_refs:
            raise HTTPException(
                status_code=400, detail=f"runtime admission node lacks capability reference: {selection.node_key}"
            )
        if capability_id is not None:
            capability = capability_repo.get_visible_for_tenant(capability_id=capability_id, tenant_id=tenant_id_str)
            if capability is None:
                raise HTTPException(status_code=400, detail=f"capability not found for tenant: {capability_id}")
        else:
            visible_capability_found = False
            for capability_ref in node_capability_refs:
                if not isinstance(capability_ref, dict):
                    continue
                capability_name = capability_ref.get("name")
                capability_version = capability_ref.get("version")
                if not isinstance(capability_name, str) or not capability_name.strip():
                    continue
                if not isinstance(capability_version, str) or not capability_version.strip():
                    continue

                capability = capability_repo.get_conflict_for_scope(
                    name=capability_name.strip(),
                    version=capability_version.strip(),
                    tenant_id=tenant_id_str,
                )
                if capability is None:
                    capability = capability_repo.get_conflict_for_scope(
                        name=capability_name.strip(),
                        version=capability_version.strip(),
                        tenant_id=None,
                    )
                if capability is not None:
                    visible_capability_found = True
                    break

            if not visible_capability_found:
                raise HTTPException(
                    status_code=400,
                    detail=f"runtime admission node lacks visible capability reference: {selection.node_key}",
                )

        adapter_id = selection.adapter_id
        if adapter_id is not None:
            adapter = adapter_repo.get_visible_for_tenant(adapter_id=adapter_id, tenant_id=tenant_id_str)
            if adapter is None:
                raise HTTPException(status_code=400, detail=f"capability adapter not found for tenant: {adapter_id}")

        validation_checks.append({"name": f"node:{selection.node_key}", "status": "passed"})
        selected_nodes.append(
            {
                "node_key": selection.node_key,
                "runtime_task_type": runtime_task_type,
                "capability_id": str(capability_id) if capability_id is not None else None,
                "adapter_id": str(adapter_id) if adapter_id is not None else None,
                "graph_node_reference": {
                    "key": node.get("key"),
                    "name": node.get("name"),
                    "intended_task_type": node.get("intended_task_type"),
                },
                "materialization_selection_reference": materialized_selection,
                "operator_notes": selection.operator_notes,
            }
        )

    previous = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    previous_version = previous.get("admission_version", 0) if isinstance(previous, dict) else 0
    now = datetime.now(UTC).isoformat()
    validation_notes = list(body.validation_notes)
    if not body.selected_nodes:
        validation_notes = [
            *validation_notes,
            "Server-derived selected_nodes from compiled task graph + bridge authority.",
        ]
    runtime_admission_metadata = build_runtime_admission_metadata(
        mission_id=str(mission_id),
        admission_status=body.admission_status,
        admission_version=previous_version + 1,
        admitted_by=admitted_by,
        admitted_at=(
            previous.get("admitted_at", now)
            if isinstance(previous, dict) and previous.get("admission_status") != "superseded"
            else now
        ),
        updated_at=now,
        graph_reference={
            "metadata_key": MISSION_TASK_GRAPH_METADATA_KEY,
            "schema_version": task_graph.get("schema_version") if isinstance(task_graph, dict) else None,
            "graph_status": task_graph.get("graph_status") if isinstance(task_graph, dict) else None,
            "graph_version": graph_version,
            "graph_fingerprint": graph_fingerprint,
            "node_count": len(graph_nodes) if isinstance(graph_nodes, list) else 0,
        },
        materialization_reference={
            "metadata_key": MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
            "schema_version": materialization.get("schema_version"),
            "materialization_status": materialization.get("materialization_status"),
            "materialization_version": materialization.get("materialization_version"),
            "graph_reference": graph_reference,
        },
        selected_nodes=selected_nodes,
        validation_result={
            "validation_status": "valid",
            "summary": (
                "Runtime admission metadata validated; queue admission and worker dispatch are recorded separately."
            ),
            "validated_at": now,
            "checks": validation_checks,
            "gaps": validation_notes,
        },
        execution_task_records=[],
        runtime_authority={
            "creates_execution_tasks": False,
            "enqueues_work": False,
            "dispatches_workers": False,
            "requires_explicit_queue_admission_for_execution": True,
        },
    )
    cancelled_task_ids: list[str] = []
    if isinstance(metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY), dict):
        cancelled_task_ids = _cancel_superseded_materialized_planned_tasks(
            metadata=metadata,
            task_repo=ExecutionTaskRepository(db),
            tenant_id=tenant_id_str,
            mission_id=mission_id,
        )
    metadata.update(runtime_admission_metadata)
    supersede_runtime_task_materialization(
        metadata=metadata,
        reason="runtime_admission_replaced",
        updated_at=now,
        supersession={
            "superseded_by_admission_version": previous_version + 1,
            "cancelled_execution_task_ids": cancelled_task_ids,
        },
    )
    mission = repo.update_metadata(mission=mission, metadata_json=metadata)
    return _runtime_admission_to_read(mission)


@router.get("/{mission_id}/runtime-readiness", response_model=RuntimeReadinessRead)
def read_mission_runtime_readiness(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeReadinessRead:
    """Validate read-only runtime admission readiness without runtime authority."""
    return _mission_runtime.read_mission_runtime_readiness(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.get("/{mission_id}/runtime-task-preview", response_model=RuntimeTaskPreviewRead)
def read_mission_runtime_task_preview(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeTaskPreviewRead:
    """Preview future ExecutionTask materialization without creating or queueing work."""
    return _mission_runtime.read_mission_runtime_task_preview(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.get("/{mission_id}/runtime-task-materialization", response_model=RuntimeTaskMaterializationRead)
def read_mission_runtime_task_materialization(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeTaskMaterializationRead:
    """Read tenant-scoped ExecutionTask materialization metadata."""
    return _mission_runtime.read_mission_runtime_task_materialization(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.post("/{mission_id}/runtime-task-materialization", response_model=RuntimeTaskMaterializationRead)
def materialize_mission_runtime_tasks(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeTaskMaterializationRead:
    """Create planned ExecutionTask rows from a ready admitted mission graph without queueing work."""
    return _mission_runtime.materialize_mission_runtime_tasks(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.get("/{mission_id}/runtime-dispatch-readiness", response_model=RuntimeDispatchReadinessRead)
def read_mission_runtime_dispatch_readiness(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeDispatchReadinessRead:
    """Read queued materialized task readiness without dispatching workers."""
    return _mission_runtime.read_mission_runtime_dispatch_readiness(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.get("/{mission_id}/worker-dispatch-eligibility", response_model=WorkerDispatchEligibilityRead)
def read_mission_worker_dispatch_eligibility(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerDispatchEligibilityRead:
    """Read worker dispatch eligibility without claiming leases or mutating runtime state."""
    return _mission_runtime.read_mission_worker_dispatch_eligibility(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.get("/{mission_id}/worker-claim-preview", response_model=WorkerClaimPreviewRead)
def read_mission_worker_claim_preview(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerClaimPreviewRead:
    """Preview future worker claim envelopes without claiming or dispatching work."""
    return _mission_runtime.read_mission_worker_claim_preview(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.post("/{mission_id}/worker-claim-admission", response_model=WorkerClaimAdmissionRead)
def worker_claim_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerClaimAdmissionRead:
    """Deprecated: daemon workers exclusively own queue claim authority."""
    return _mission_runtime.worker_claim_admission(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.get("/{mission_id}/worker-claim-admission", response_model=WorkerClaimAdmissionRead)
def read_mission_worker_claim_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerClaimAdmissionRead:
    """Read latest worker claim admission metadata without mutating runtime state."""
    return _mission_runtime.read_mission_worker_claim_admission(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.post("/{mission_id}/worker-start-admission", response_model=WorkerStartAdmissionRead)
def worker_start_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerStartAdmissionRead:
    """Deprecated: daemon workers exclusively own execution start authority."""
    return _mission_runtime.worker_start_admission(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.get("/{mission_id}/worker-start-admission", response_model=WorkerStartAdmissionRead)
def read_mission_worker_start_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerStartAdmissionRead:
    """Read latest worker execution start admission metadata without mutating runtime state."""
    return _mission_runtime.read_mission_worker_start_admission(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.post("/{mission_id}/worker-run-admission", response_model=WorkerRunAdmissionRead)
def worker_run_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerRunAdmissionRead:
    """Deprecated: daemon workers exclusively own dispatcher execution authority."""
    return _mission_runtime.worker_run_admission(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.get("/{mission_id}/worker-run-admission", response_model=WorkerRunAdmissionRead)
def read_mission_worker_run_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> WorkerRunAdmissionRead:
    """Read latest worker run admission metadata without mutating runtime state."""
    return _mission_runtime.read_mission_worker_run_admission(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.post("/{mission_id}/runtime-queue-admission", response_model=RuntimeQueueAdmissionResponse)
def runtime_queue_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, object]:
    """Queue eligible planned tasks from the current runtime task materialization."""
    return _mission_runtime.runtime_queue_admission(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        queue=queue,
        deps=_runtime_route_dependencies(),
    )


def _admit_mission_runtime_queue(
    *, mission_id: UUID, tenant_id: _uuid.UUID, db: Session, queue: QueueAdapter
) -> dict[str, object]:
    """Invoke the single canonical mission runtime queue-admission authority."""
    return _mission_runtime.admit_mission_runtime_queue(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        queue=queue,
        deps=_runtime_route_dependencies(),
    )


@router.get("/{mission_id}/runtime-admission", response_model=RuntimeAdmissionRead)
def read_mission_runtime_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeAdmissionRead:
    """Read tenant-scoped graph-to-runtime admission metadata."""
    return _mission_runtime.read_mission_runtime_admission(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.post("/{mission_id}/bridge-runtime-authority", response_model=BridgeRuntimeAuthorityRead)
def provision_mission_bridge_runtime_authority(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BridgeRuntimeAuthorityRead:
    """Provision tenant-scoped capability/adapter authority for mission bridge tool.invoke nodes."""
    return _mission_runtime.provision_mission_bridge_runtime_authority(
        mission_id=mission_id,
        request=request,
        tenant_id=tenant_id,
        db=db,
        deps=_runtime_route_dependencies(),
    )


@router.post(
    "/{mission_id}/queue",
    response_model=MissionQueueResponse,
    deprecated=True,
    summary="[Legacy] Compatibility wrapper for runtime queue admission",
)
def queue_mission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, object]:
    """Delegate to canonical runtime queue admission and project the legacy response."""
    logger.info(
        "legacy_mission_queue_route_used",
        extra={"mission_id": str(mission_id), "tenant_id": str(tenant_id), "legacy_route": "missions.queue"},
    )
    require_route_permission(request=request, db=db, permission=Permission.EXECUTION_QUEUE, tenant_id=tenant_id)
    admission = _admit_mission_runtime_queue(
        mission_id=mission_id,
        tenant_id=tenant_id,
        db=db,
        queue=queue,
    )
    return {
        "queued_task_ids": admission["queued_task_ids"],
        "pending_review_task_ids": admission["pending_review_task_ids"],
        "denied_tasks": admission["denied_tasks"],
    }


@router.post("/{mission_id}/cancel")
def cancel_mission(
    mission_id: UUID,
    body: MissionCancelRequest,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, Any]:
    """Stop a mission and terminalize cancellable graph work."""
    require_route_permission(request=request, db=db, permission=Permission.MISSION_MANAGE, tenant_id=tenant_id)
    principal = getattr(request.state, "principal", None)
    actor = str(getattr(principal, "subject_id", "operator"))
    try:
        return WorkerRuntimeService(db, queue).cancel_mission(
            tenant_id=str(tenant_id), mission_id=mission_id, actor=actor, reason=body.reason.strip()
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# Contract-test patch targets for mission_bridge re-exports.
# Compatibility patch targets for older contract fixtures. Runtime dispatch
# remains owned by the daemon worker and these names are never invoked here.
TaskDispatcher = None
WorkerLeaseRepository = None
_TEST_PATCH_EXPORTS = (
    WorkerLease,
    _mission_runtime._tenant_aware_dispatcher_session_factory,
    _mission_runtime._worker_run_admission_authority_flags,
)
