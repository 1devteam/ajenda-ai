"""Tenant-scoped read API for the assembled RevOps mission deliverable."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.domain.audit_event import AuditEvent
from backend.domain.execution_task import ExecutionTask
from backend.domain.knowledge_change_proposal import KnowledgeChangeProposalRecord
from backend.domain.worker_lease import WorkerLease
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.knowledge_change_proposal_repository import KnowledgeChangeProposalRepository
from backend.repositories.lineage_record_repository import LineageRecordRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.outcome_review_repository import OutcomeReviewRepository
from backend.services.document_artifacts import read_artifact
from backend.services.knowledge.knowledge_change_proposals import (
    KnowledgeChangeProposalSet,
    build_knowledge_change_proposals,
    proposal_from_record,
)
from backend.services.knowledge.tenant_knowledge_application import (
    TenantKnowledgeApplicationError,
    TenantKnowledgeApplicationResult,
    TenantKnowledgeApplicationService,
)
from backend.services.mission_composition.deliverable_runtime_artifacts import collect_materialized_artifacts
from backend.services.mission_composition.deliverable_runtime_state import load_deliverable_runtime_state
from backend.services.mission_composition.profile_deliverable import (
    ProfileDeliverableRead,
    assemble_profile_deliverable,
)
from backend.services.mission_composition.revops_deliverable import (
    RevOpsMissionDeliverableRead,
    assemble_revops_mission_deliverable,
)
from backend.services.mission_runtime_evidence_projection import (
    MissionRuntimeEvidenceProjection,
    build_mission_runtime_evidence_projection,
)

router = APIRouter(prefix="/missions", tags=["missions"])


class KnowledgeChangeProposalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(accepted|rejected|superseded|rolled_back)$")
    superseding_proposal_id: str | None = Field(default=None, max_length=160)
    rollback_of_proposal_id: str | None = Field(default=None, max_length=160)
    accepted_fact: dict[str, object] | None = None
    note: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def require_bound_fact_for_acceptance(self) -> KnowledgeChangeProposalReviewRequest:
        if self.status == "accepted" and not self.accepted_fact:
            raise ValueError("accepted_fact is required when accepting a tenant-private proposal")
        return self


class TenantKnowledgeApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_fact: dict[str, object] = Field(min_length=1)
    note: str = Field(min_length=1, max_length=2_000)


def _runtime_state_from_metadata(metadata: object) -> object | None:
    if not isinstance(metadata, dict):
        return None
    intake = metadata.get("mission_intake")
    if not isinstance(intake, dict):
        return None
    context = intake.get("context")
    if not isinstance(context, dict):
        return None
    composition = context.get("composition")
    if not isinstance(composition, dict):
        return None
    return composition.get("deliverable_runtime_state")


@router.get("/{mission_id}/knowledge-change-proposals", response_model=KnowledgeChangeProposalSet)
def read_knowledge_change_proposals(
    mission_id: uuid.UUID,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> KnowledgeChangeProposalSet:
    """Expose evidence-backed knowledge suggestions without applying them."""

    require_route_permission(request=request, db=db, permission=Permission.RUNTIME_VIEW, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    reviews = OutcomeReviewRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    metadata = mission.metadata_json if isinstance(mission.metadata_json, dict) else {}
    try:
        runtime_state = load_deliverable_runtime_state(_runtime_state_from_metadata(metadata))
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail="mission deliverable runtime state is invalid") from exc
    return build_knowledge_change_proposals(
        tenant_id=tenant_scope,
        mission_id=mission_id,
        reviews=reviews,
        runtime_state=runtime_state,
    )


@router.post(
    "/{mission_id}/knowledge-change-proposals/materialize",
    response_model=KnowledgeChangeProposalSet,
    status_code=status.HTTP_201_CREATED,
)
def materialize_knowledge_change_proposals(
    mission_id: uuid.UUID,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> KnowledgeChangeProposalSet:
    """Persist the review-only projection and append provenance audit events."""

    require_route_permission(request=request, db=db, permission=Permission.OUTCOME_REVIEW_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    reviews = OutcomeReviewRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    metadata = mission.metadata_json if isinstance(mission.metadata_json, dict) else {}
    try:
        runtime_state = load_deliverable_runtime_state(_runtime_state_from_metadata(metadata))
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail="mission deliverable runtime state is invalid") from exc
    projected = build_knowledge_change_proposals(
        tenant_id=tenant_scope, mission_id=mission_id, reviews=reviews, runtime_state=runtime_state
    )
    repository = KnowledgeChangeProposalRepository(db)
    actor_id = str(getattr(getattr(request.state, "principal", None), "subject_id", "unknown"))
    records = []
    try:
        for proposal in projected.proposals:
            if repository.get(tenant_id=tenant_scope, proposal_id=proposal.proposal_id) is not None:
                continue
            records.append(
                repository.add(
                    KnowledgeChangeProposalRecord(
                        tenant_id=tenant_scope,
                        proposal_id=proposal.proposal_id,
                        mission_id=mission_id,
                        review_id=proposal.review_id,
                        scope=proposal.scope,
                        target_key=proposal.target_key,
                        suggested_change=proposal.suggested_change,
                        rationale=proposal.rationale,
                        evidence_references=list(proposal.evidence_references),
                        source_artifact_ids=list(proposal.source_artifact_ids),
                        runtime_reconciliation=proposal.runtime_reconciliation,
                        confidence=proposal.confidence,
                        provenance={"source": "outcome_review", "actor_id": actor_id},
                    )
                )
            )
            AuditEventRepository(db).append(
                AuditEvent(
                    tenant_id=tenant_scope,
                    mission_id=mission_id,
                    category="knowledge_change_proposal",
                    action="materialized",
                    actor=actor_id,
                    details="Materialized review-only knowledge-change proposal.",
                    payload_json={"proposal_id": proposal.proposal_id, "review_id": str(proposal.review_id)},
                )
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="knowledge-change proposal materialization failed") from exc
    return KnowledgeChangeProposalSet(
        mission_id=mission_id,
        proposals=tuple(proposal_from_record(record) for record in records),
    )


@router.post(
    "/{mission_id}/knowledge-change-proposals/{proposal_id}/review",
    response_model=KnowledgeChangeProposalSet,
)
def review_knowledge_change_proposal(
    mission_id: uuid.UUID,
    proposal_id: str,
    body: KnowledgeChangeProposalReviewRequest,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> KnowledgeChangeProposalSet:
    """Record a human lifecycle decision without applying knowledge or runtime work."""

    require_route_permission(request=request, db=db, permission=Permission.OUTCOME_REVIEW_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    record = KnowledgeChangeProposalRepository(db).get(tenant_id=tenant_scope, proposal_id=proposal_id)
    if record is None or record.mission_id != mission_id:
        raise HTTPException(status_code=404, detail="knowledge-change proposal not found for tenant")
    actor_id = str(getattr(getattr(request.state, "principal", None), "subject_id", "unknown"))
    try:
        KnowledgeChangeProposalRepository(db).transition(
            record=record,
            status=body.status,
            actor_id=actor_id,
            provenance={
                "review_note": body.note,
                "reviewed_at": datetime.now(UTC).isoformat(),
                **({"rollback_effect": "review_only"} if body.status == "rolled_back" else {}),
                **(
                    {
                        "accepted_fact": body.accepted_fact,
                        "accepted_fact_sha256": hashlib.sha256(
                            json.dumps(body.accepted_fact, sort_keys=True, separators=(",", ":")).encode()
                        ).hexdigest(),
                    }
                    if body.status == "accepted" and body.accepted_fact is not None
                    else {}
                ),
            },
            superseded_by_proposal_id=body.superseding_proposal_id,
            rollback_of_proposal_id=body.rollback_of_proposal_id,
        )
        AuditEventRepository(db).append(
            AuditEvent(
                tenant_id=tenant_scope,
                mission_id=mission_id,
                category="knowledge_change_proposal",
                action=body.status,
                actor=actor_id,
                details=body.note,
                payload_json={"proposal_id": proposal_id, "rollback_of": body.rollback_of_proposal_id},
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="knowledge-change proposal review failed") from exc
    return KnowledgeChangeProposalSet(mission_id=mission_id, proposals=(proposal_from_record(record),))


@router.post(
    "/{mission_id}/knowledge-change-proposals/{proposal_id}/apply-tenant-private",
    response_model=TenantKnowledgeApplicationResult,
)
def apply_tenant_private_knowledge_proposal(
    mission_id: uuid.UUID,
    proposal_id: str,
    body: TenantKnowledgeApplyRequest,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> TenantKnowledgeApplicationResult:
    """Apply one accepted tenant-private fact through the profile authority owner."""

    require_route_permission(request=request, db=db, permission=Permission.OUTCOME_REVIEW_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    proposal = KnowledgeChangeProposalRepository(db).get(tenant_id=tenant_scope, proposal_id=proposal_id)
    if proposal is None or proposal.mission_id != mission_id:
        raise HTTPException(status_code=404, detail="knowledge-change proposal not found for tenant")
    profile = BusinessProfileRepository(db).get_active_profile_for_tenant(tenant_id=tenant_scope)
    if profile is None:
        raise HTTPException(status_code=409, detail="active tenant business profile is required")
    actor_id = str(getattr(getattr(request.state, "principal", None), "subject_id", "unknown"))
    try:
        result = TenantKnowledgeApplicationService().apply(
            db,
            proposal=proposal,
            profile=profile,
            approved_fact=dict(body.approved_fact),
            actor_id=actor_id,
            note=body.note,
        )
        db.commit()
        return result
    except TenantKnowledgeApplicationError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="tenant knowledge application failed") from exc


def _draft_artifact_ids(tasks: list[ExecutionTask]) -> tuple[str, ...]:
    """Return stable draft IDs from the canonical completed draft artifact."""

    artifacts = collect_materialized_artifacts(tasks)
    drafts = next(
        (artifact for artifact in artifacts if artifact.artifact_key == "introduction_drafts"),
        None,
    )
    if drafts is None or not isinstance(drafts.payload, list):
        return ()
    artifact_ids: list[str] = []
    for row in drafts.payload:
        if not isinstance(row, dict):
            continue
        artifact_id = row.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id.strip() and artifact_id.strip() not in artifact_ids:
            artifact_ids.append(artifact_id.strip())
    return tuple(artifact_ids)


@router.get("/{mission_id}/deliverable", response_model=RevOpsMissionDeliverableRead)
def read_revops_mission_deliverable(
    mission_id: uuid.UUID,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RevOpsMissionDeliverableRead:
    """Assemble the current artifact-backed RevOps report without runtime mutation."""

    _ = request
    tenant_scope = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    tasks = ExecutionTaskRepository(db).list_for_mission_for_tenant(
        mission_id=mission_id,
        tenant_id=tenant_scope,
    )
    document_artifacts = {}
    for artifact_id in _draft_artifact_ids(tasks):
        artifact = read_artifact(db, tenant_id=tenant_scope, artifact_id=artifact_id)
        if artifact is not None:
            document_artifacts[artifact_id] = artifact

    evidence = EvidenceRepository(db).list_for_mission(
        mission_id=mission_id,
        tenant_id=tenant_scope,
    )
    reviews = OutcomeReviewRepository(db).list_for_mission(
        mission_id=mission_id,
        tenant_id=tenant_scope,
    )
    try:
        return assemble_revops_mission_deliverable(
            mission=mission,
            tasks=tasks,
            document_artifacts=document_artifacts,
            evidence_records=evidence,
            outcome_reviews=reviews,
        )
    except (ValidationError, ValueError) as exc:
        if str(exc) == "mission deliverable runtime state is absent":
            raise HTTPException(status_code=404, detail="mission deliverable runtime state not found") from exc
        raise HTTPException(status_code=409, detail="mission deliverable assembly is invalid") from exc


@router.get("/{mission_id}/profile-deliverable", response_model=ProfileDeliverableRead)
def read_profile_mission_deliverable(
    mission_id: uuid.UUID,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ProfileDeliverableRead:
    """Assemble the approved business-profile mission artifact without mutation."""

    _ = request
    tenant_scope = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    tasks = ExecutionTaskRepository(db).list_for_mission_for_tenant(
        mission_id=mission_id,
        tenant_id=tenant_scope,
    )
    evidence = EvidenceRepository(db).list_for_mission(
        mission_id=mission_id,
        tenant_id=tenant_scope,
    )
    try:
        return assemble_profile_deliverable(
            mission=mission,
            tasks=tasks,
            evidence_records=evidence,
        )
    except ValueError as exc:
        if str(exc) == "business profile deliverable artifact is absent":
            raise HTTPException(status_code=404, detail="business profile deliverable artifact not found") from exc
        raise HTTPException(status_code=409, detail="business profile deliverable assembly is invalid") from exc


@router.get("/{mission_id}/runtime-evidence", response_model=MissionRuntimeEvidenceProjection)
def read_mission_runtime_evidence(
    mission_id: uuid.UUID,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionRuntimeEvidenceProjection:
    """Expose persisted runtime facts for GRAFT review without executing work."""

    tenant_scope = str(tenant_id)
    require_route_permission(request=request, db=db, permission=Permission.RUNTIME_VIEW, tenant_id=tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    tasks = ExecutionTaskRepository(db).list_for_mission_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    task_ids = [task.id for task in tasks]
    leases = (
        list(
            db.scalars(
                select(WorkerLease).where(WorkerLease.tenant_id == tenant_scope, WorkerLease.task_id.in_(task_ids))
            )
        )
        if task_ids
        else []
    )
    lineage = LineageRecordRepository(db).list_for_mission_for_tenant(
        mission_id=mission_id,
        tenant_id=tenant_scope,
    )
    evidence = EvidenceRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    audit_events = AuditEventRepository(db).list_for_mission_for_tenant(
        mission_id=mission_id,
        tenant_id=tenant_scope,
    )
    return build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_scope,
        mission_status=mission.status,
        mission_metadata=mission.metadata_json if isinstance(mission.metadata_json, dict) else {},
        tasks=tasks,
        leases=leases,
        lineage=lineage,
        evidence=evidence,
        audit_events=audit_events,
    )
