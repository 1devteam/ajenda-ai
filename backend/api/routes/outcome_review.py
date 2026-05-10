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


class OutcomeEvidenceReference(BaseModel):
    """Reference to evidence used by an outcome review."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    relationship: str = Field(default="supports", min_length=1, max_length=64)
    success_criteria_keys: list[str] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, min_length=1, max_length=1000)

    @field_validator("relationship", "notes")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty when provided")
        return value

    @field_validator("success_criteria_keys")
    @classmethod
    def _normalize_success_criteria_keys(cls, value: list[str]) -> list[str]:
        return _normalize_unique_string_list(value)


class OutcomeReviewCreate(BaseModel):
    """Create a tenant-owned outcome review record without runtime side effects."""

    model_config = ConfigDict(extra="forbid")

    mission_id: UUID
    outcome_ref: dict[str, Any] = Field(default_factory=dict)
    materialization_reference: dict[str, Any] | None = None
    task_graph_reference: dict[str, Any] | None = None
    reviewed_success_criteria: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    evidence_references: list[OutcomeEvidenceReference] = Field(default_factory=list, max_length=100)
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
    human_approval_status: HumanApprovalStatus = "not_required"

    @field_validator("reviewer_source", "review_summary")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty")
        return value

    @model_validator(mode="after")
    def _validate_human_approval_status(self) -> OutcomeReviewCreate:
        if self.human_approval_required and self.human_approval_status == "not_required":
            raise ValueError("human approval status cannot be not_required when approval is required")
        if not self.human_approval_required and self.human_approval_status != "not_required":
            raise ValueError("human approval status must be not_required when approval is not required")
        return self


class OutcomeReviewUpdate(BaseModel):
    """Update mutable outcome review status and review metadata only."""

    model_config = ConfigDict(extra="forbid")

    review_status: ReviewStatus | None = None
    review_decision: ReviewDecision | None = None
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
        nullable_fields = {"confidence"}
        null_fields = [
            field for field in self.model_fields_set if field not in nullable_fields and getattr(self, field) is None
        ]
        if null_fields:
            joined_fields = ", ".join(sorted(null_fields))
            raise ValueError(f"outcome review patch fields cannot be null: {joined_fields}")
        if self.human_approval_required is False and self.human_approval_status not in (None, "not_required"):
            raise ValueError("human approval status must be not_required when approval is not required")
        if self.human_approval_required is True and self.human_approval_status == "not_required":
            raise ValueError("human approval status cannot be not_required when approval is required")
        return self

    @field_validator("review_summary")
    @classmethod
    def _normalize_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("review_summary must be non-empty when provided")
        return value


class OutcomeReviewRead(BaseModel):
    """Outcome review record response contract."""

    review_id: UUID
    tenant_id: str
    mission_id: UUID
    outcome_ref: dict[str, Any]
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
    human_approval_status: str
    schema_version: int
    created_at: str
    updated_at: str


class OutcomeReviewListRead(BaseModel):
    """List response for outcome review records."""

    outcome_reviews: list[OutcomeReviewRead]


def _normalize_unique_string_list(value: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized_item = item.strip()
        if not normalized_item:
            raise ValueError("list values must be non-empty")
        if normalized_item not in seen:
            normalized.append(normalized_item)
            seen.add(normalized_item)
    return normalized


def _isoformat(value: datetime) -> str:
    return value.isoformat()


def _review_to_read(review: OutcomeReview) -> OutcomeReviewRead:
    return OutcomeReviewRead(
        review_id=review.id,
        tenant_id=review.tenant_id,
        mission_id=review.mission_id,
        outcome_ref=review.outcome_ref,
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


def _serialized_evidence_references(references: list[OutcomeEvidenceReference]) -> list[dict[str, Any]]:
    return [reference.model_dump(mode="json") for reference in references]


def _validate_references(
    *, mission_id: UUID, evidence_references: list[OutcomeEvidenceReference], tenant_id: str, db: Session
) -> None:
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    evidence_repo = EvidenceRepository(db)
    for reference in evidence_references:
        evidence = evidence_repo.get_for_tenant(evidence_id=reference.evidence_id, tenant_id=tenant_id)
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
    """Persist an outcome review contract without runtime side effects."""
    tenant_scope = str(tenant_id)
    _validate_references(
        mission_id=body.mission_id,
        evidence_references=body.evidence_references,
        tenant_id=tenant_scope,
        db=db,
    )

    review = OutcomeReviewRepository(db).add(
        OutcomeReview(
            tenant_id=tenant_scope,
            mission_id=body.mission_id,
            outcome_ref=body.outcome_ref,
            materialization_reference=body.materialization_reference,
            task_graph_reference=body.task_graph_reference,
            reviewed_success_criteria=body.reviewed_success_criteria,
            evidence_references=_serialized_evidence_references(body.evidence_references),
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
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
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
    repo = OutcomeReviewRepository(db)
    review = repo.get_for_tenant(review_id=review_id, tenant_id=str(tenant_id))
    if review is None:
        raise HTTPException(status_code=404, detail="outcome review not found for tenant")

    updates = body.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        setattr(review, field_name, value)

    if not review.human_approval_required and review.human_approval_status != "not_required":
        raise HTTPException(
            status_code=422, detail="human approval status must be not_required when approval is not required"
        )
    if review.human_approval_required and review.human_approval_status == "not_required":
        raise HTTPException(
            status_code=422, detail="human approval status cannot be not_required when approval is required"
        )

    return _review_to_read(repo.update(review))
