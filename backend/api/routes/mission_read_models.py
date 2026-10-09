"""Mission route read-model and lifecycle projections."""

from datetime import datetime, UTC
from typing import Any

from fastapi import HTTPException

from backend.api.routes import mission_contracts as _mission_contracts
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import (
    Mission,
    MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
    MISSION_INTAKE_METADATA_KEY,
    MISSION_PLAN_METADATA_KEY,
    MISSION_RUNTIME_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
    mission_task_graph_allows_legacy_v1,
    MISSION_TASK_GRAPH_METADATA_KEY,
    MISSION_WORKER_CLAIM_ADMISSION_METADATA_KEY,
    MISSION_WORKER_RUN_ADMISSION_METADATA_KEY,
    MISSION_WORKER_START_ADMISSION_METADATA_KEY,
    MissionPlan,
    normalize_mission_plan_contract_metadata,
    normalize_mission_task_graph_contract_metadata,
)
from backend.services.mission_composition.deliverable_runtime_observability import (
    build_deliverable_runtime_state_read,
)

MissionTaskGraphRead = _mission_contracts.MissionTaskGraphRead
GraphMaterializationRead = _mission_contracts.GraphMaterializationRead
RuntimeAdmissionRead = _mission_contracts.RuntimeAdmissionRead
MissionPlanRead = _mission_contracts.MissionPlanRead
MissionRead = _mission_contracts.MissionRead
MissionListItem = _mission_contracts.MissionListItem
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


def _runtime_admission_to_read(mission: Mission) -> RuntimeAdmissionRead:
    return RuntimeAdmissionRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        runtime_admission=mission.metadata_json.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY, {}),
        updated_at=mission.updated_at.isoformat(),
    )

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
