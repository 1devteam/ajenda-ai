from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.domain.outcome_review import OUTCOME_REVIEW_SCHEMA_VERSION, OutcomeReview
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.outcome_review_repository import OutcomeReviewRepository

router = APIRouter(prefix="/outcome-reviews", tags=["outcome-reviews"])

ReviewStatus = Literal["draft", "in_review", "completed", "superseded"]
ReviewDecision = Literal["accepted", "rejected", "partial", "inconclusive", "needs_human_review"]
ReviewerType = Literal["operator", "system", "policy", "external"]
HumanApprovalStatus = Literal["not_required", "pending", "approved", "rejected"]


def _validate_evidence_reference_shape(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, reference in enumerate(references):
        evidence_id = reference.get("evidence_id")
        if evidence_id is None:
            raise ValueError(f"evidence_references[{index}] must include evidence_id")
        try:
            UUID(str(evidence_id))
        except ValueError as exc:
            raise ValueError(f"evidence_references[{index}].evidence_id must be a UUID") from exc
    return references


class OutcomeReviewCreate(BaseModel):
    """Create a tenant-owned outcome review record without runtime side effects."""

    model_config = ConfigDict(extra="forbid")

    mission_id: UUID
    materialization_reference: dict[str, Any] | None = None
    task_graph_reference: dict[str, Any] | None = None
    reviewed_success_criteria: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    evidence_references: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    review_status: ReviewStatus = "draft"
    review_decision: ReviewDecision = "inconclusive"
    reviewer_type: ReviewerType
    reviewer_source: str = Field(min_length=1, max_length=160)
    review_summary: str = Field(min_length=1, max_length=5000)
    structured_findings: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    trust_signal: dict[str, Any] = Field(default_factory=dict)
    unresolved_gaps: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    recommended_next_actions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    human_approval_required: bool = False
    human_approval_status: HumanApprovalStatus | None = None

    @field_validator("reviewer_source", "review_summary")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty")
        return value

    @field_validator("evidence_references")
    @classmethod
    def _validate_evidence_references(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _validate_evidence_reference_shape(value)


class OutcomeReviewUpdate(BaseModel):
    """Update mutable outcome review status and metadata fields only."""

    model_config = ConfigDict(extra="forbid")

    materialization_reference: dict[str, Any] | None = None
    task_graph_reference: dict[str, Any] | None = None
    reviewed_success_criteria: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    evidence_references: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    review_status: ReviewStatus | None = None
    review_decision: ReviewDecision | None = None
    reviewer_source: str | None = Field(default=None, min_length=1, max_length=160)
    review_summary: str | None = Field(default=None, min_length=1, max_length=5000)
    structured_findings: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    trust_signal: dict[str, Any] | None = None
    unresolved_gaps: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    recommended_next_actions: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    human_approval_required: bool | None = None
    human_approval_status: HumanApprovalStatus | None = None

    @model_validator(mode="after")
    def _reject_explicit_null_patch_values(self) -> OutcomeReviewUpdate:
        nullable_fields = {"materialization_reference", "task_graph_reference", "confidence", "human_approval_status"}
        null_fields = [
            field for field in self.model_fields_set if field not in nullable_fields and getattr(self, field) is None
        ]
        if null_fields:
            joined_fields = ", ".join(sorted(null_fields))
            raise ValueError(f"outcome review patch fields cannot be null: {joined_fields}")
        return self

    @field_validator("reviewer_source", "review_summary")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty when provided")
        return value

    @field_validator("evidence_references")
    @classmethod
    def _validate_evidence_references(cls, value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if value is None:
            return None
        return _validate_evidence_reference_shape(value)


class OutcomeReviewRead(BaseModel):
    """Outcome review record response contract."""

    review_id: UUID
    tenant_id: str
    mission_id: UUID
    materialization_reference: dict[str, Any] | None
    task_graph_reference: dict[str, Any] | None
    reviewed_success_criteria: list[dict[str, Any]]
    evidence_references: list[dict[str, Any]]
    review_status: str
    review_decision: str
    reviewer_type: str
    reviewer_source: str
    review_summary: str
    structured_findings: list[dict[str, Any]]
    confidence: float | None
    trust_signal: dict[str, Any]
    unresolved_gaps: list[dict[str, Any]]
    recommended_next_actions: list[dict[str, Any]]
    human_approval_required: bool
    human_approval_status: str | None
    schema_version: int
    created_at: str
    updated_at: str


class OutcomeReviewListRead(BaseModel):
    """List response for outcome review records."""

    outcome_reviews: list[OutcomeReviewRead]


def _isoformat(value: datetime) -> str:
    return value.isoformat()


def _review_to_read(review: OutcomeReview) -> OutcomeReviewRead:
    return OutcomeReviewRead(
        review_id=review.id,
        tenant_id=review.tenant_id,
        mission_id=review.mission_id,
        materialization_reference=review.materialization_reference,
        task_graph_reference=review.task_graph_reference,
        reviewed_success_criteria=review.reviewed_success_criteria,
        evidence_references=review.evidence_references,
        review_status=review.review_status,
        review_decision=review.review_decision,
        reviewer_type=review.reviewer_type,
        reviewer_source=review.reviewer_source,
        review_summary=review.review_summary,
        structured_findings=review.structured_findings,
        confidence=review.confidence,
        trust_signal=review.trust_signal,
        unresolved_gaps=review.unresolved_gaps,
        recommended_next_actions=review.recommended_next_actions,
        human_approval_required=review.human_approval_required,
        human_approval_status=review.human_approval_status,
        schema_version=review.schema_version,
        created_at=_isoformat(review.created_at),
        updated_at=_isoformat(review.updated_at),
    )


def _validate_mission(*, mission_id: UUID, tenant_id: str, db: Session) -> None:
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")


def _validate_evidence_references_for_mission(
    *, evidence_references: list[dict[str, Any]], mission_id: UUID, tenant_id: str, db: Session
) -> None:
    evidence_repo = EvidenceRepository(db)
    for reference in evidence_references:
        evidence_id = UUID(str(reference["evidence_id"]))
        evidence = evidence_repo.get_for_tenant(evidence_id=evidence_id, tenant_id=tenant_id)
        if evidence is None:
            raise HTTPException(status_code=422, detail="referenced evidence is not owned by tenant mission")
        if evidence.mission_id != mission_id:
            raise HTTPException(status_code=422, detail="referenced evidence is not owned by tenant mission")


@router.post("", response_model=OutcomeReviewRead, status_code=status.HTTP_201_CREATED)
def create_outcome_review(
    body: OutcomeReviewCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> OutcomeReviewRead:
    """Persist an evidence-backed outcome review contract without runtime side effects."""
    tenant_scope = str(tenant_id)
    _validate_mission(mission_id=body.mission_id, tenant_id=tenant_scope, db=db)
    _validate_evidence_references_for_mission(
        evidence_references=body.evidence_references, mission_id=body.mission_id, tenant_id=tenant_scope, db=db
    )

    review = OutcomeReviewRepository(db).add(
        OutcomeReview(
            tenant_id=tenant_scope,
            mission_id=body.mission_id,
            materialization_reference=body.materialization_reference,
            task_graph_reference=body.task_graph_reference,
            reviewed_success_criteria=body.reviewed_success_criteria,
            evidence_references=body.evidence_references,
            review_status=body.review_status,
            review_decision=body.review_decision,
            reviewer_type=body.reviewer_type,
            reviewer_source=body.reviewer_source,
            review_summary=body.review_summary,
            structured_findings=body.structured_findings,
            confidence=body.confidence,
            trust_signal=body.trust_signal,
            unresolved_gaps=body.unresolved_gaps,
            recommended_next_actions=body.recommended_next_actions,
            human_approval_required=body.human_approval_required,
            human_approval_status=body.human_approval_status,
            schema_version=OUTCOME_REVIEW_SCHEMA_VERSION,
        )
    )
    return _review_to_read(review)


@router.get("", response_model=OutcomeReviewListRead)
def list_outcome_reviews(
    request: Request,
    mission_id: UUID = Query(...),
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> OutcomeReviewListRead:
    """List tenant-owned outcome reviews for a tenant-owned mission."""
    tenant_scope = str(tenant_id)
    _validate_mission(mission_id=mission_id, tenant_id=tenant_scope, db=db)
    records = OutcomeReviewRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    return OutcomeReviewListRead(outcome_reviews=[_review_to_read(record) for record in records])


@router.get("/{review_id}", response_model=OutcomeReviewRead)
def read_outcome_review(
    review_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> OutcomeReviewRead:
    """Read one tenant-owned outcome review record."""
    review = OutcomeReviewRepository(db).get_for_tenant(review_id=review_id, tenant_id=str(tenant_id))
    if review is None:
        raise HTTPException(status_code=404, detail="outcome review not found for tenant")
    return _review_to_read(review)


@router.patch("/{review_id}", response_model=OutcomeReviewRead)
def update_outcome_review(
    review_id: UUID,
    body: OutcomeReviewUpdate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> OutcomeReviewRead:
    """Update mutable outcome review status/metadata fields without runtime side effects."""
    tenant_scope = str(tenant_id)
    repo = OutcomeReviewRepository(db)
    review = repo.get_for_tenant(review_id=review_id, tenant_id=tenant_scope)
    if review is None:
        raise HTTPException(status_code=404, detail="outcome review not found for tenant")

    updates = body.model_dump(exclude_unset=True)
    if "evidence_references" in updates:
        _validate_evidence_references_for_mission(
            evidence_references=updates["evidence_references"],
            mission_id=review.mission_id,
            tenant_id=tenant_scope,
            db=db,
        )
    for field_name, value in updates.items():
        setattr(review, field_name, value)

    return _review_to_read(repo.update(review))
