"""Typed read models for the RevOps mission deliverable."""

from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field

from backend.services.mission_composition.deliverable_contract import DeliverableFieldKey
from backend.services.tools.schemas import SideEffectClass

class RevOpsObservedContactRead(BaseModel):
    """One contact value observed in a materialized research artifact."""

    model_config = ConfigDict(extra="forbid")

    kind: str | None = None
    value: str | None = None
    source_url: str | None = None
    real: bool = False

class RevOpsDraftRead(BaseModel):
    """One materialized outreach draft and its current review state."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str | None = None
    prospect_id: str | None = None
    company_name: str | None = None
    recipient: str | None = None
    subject: str | None = None
    body: str | None = None
    review_status: Literal["pending", "approved", "rejected", "sent", "unresolved"] = "unresolved"
    recipient_bound: bool = False

class RevOpsProspectRead(BaseModel):
    """Artifact-backed final report row for one prospect identity."""

    model_config = ConfigDict(extra="forbid")

    prospect_id: str | None = None
    company_name: str | None = None
    website: str | None = None
    product_description: str | None = None
    research_summary: str | None = None
    sources: tuple[str, ...] = ()
    observed_contacts: tuple[RevOpsObservedContactRead, ...] = ()
    qualification_evidence: dict[str, Any] | None = None
    ajenda_relevance: str | None = None
    qualification_score: int | None = None
    qualification_reasons: tuple[str, ...] = ()
    drafts: tuple[RevOpsDraftRead, ...] = ()

class RevOpsDraftApprovalRead(BaseModel):
    """Current review authority state for one persisted draft artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str | None = None
    status: Literal["pending", "approved", "rejected", "sent", "unresolved"]

class RevOpsTaskApprovalRead(BaseModel):
    """Descriptive state of one task-bound side-effect approval."""

    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    action: str | None = None
    task_status: str
    status: Literal["pending", "approved", "consumed", "expired", "revoked", "invalid"]
    grant_id: uuid.UUID | None = None
    approved_by: str | None = None
    expires_at: datetime | None = None

class RevOpsOutcomeReviewRead(BaseModel):
    """Compact outcome-review state included in the final report."""

    model_config = ConfigDict(extra="forbid")

    review_id: uuid.UUID
    review_status: str
    review_decision: str
    human_approval_required: bool
    human_approval_status: str | None = None

class RevOpsApprovalStateRead(BaseModel):
    """All observable review gates without granting or consuming authority."""

    model_config = ConfigDict(extra="forbid")

    draft_approvals: tuple[RevOpsDraftApprovalRead, ...] = ()
    task_approvals: tuple[RevOpsTaskApprovalRead, ...] = ()
    outcome_reviews: tuple[RevOpsOutcomeReviewRead, ...] = ()
    all_required_approved: bool = True
    grants_execution_authority: Literal[False] = False

class RevOpsEffectRead(BaseModel):
    """Persisted result of one side-effect-classified task."""

    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    action: str | None = None
    side_effect_class: SideEffectClass
    task_status: str
    status: str
    real: bool
    provider: str | None = None
    receipt_status: Literal["recorded", "missing", "simulated", "not_applicable"]
    receipt: dict[str, Any] | None = None
    evidence_ids: tuple[uuid.UUID, ...] = ()

class RevOpsEvidenceReferenceRead(BaseModel):
    """Compact durable evidence reference for the assembled report."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: uuid.UUID
    execution_task_id: uuid.UUID | None = None
    evidence_type: str
    evidence_source: str
    summary: str
    confidence: float | None = None
    collection_status: str

class RevOpsTaskStateRead(BaseModel):
    """Task state kept explicitly separate from deliverable completion."""

    model_config = ConfigDict(extra="forbid")

    task_count: int = 0
    statuses: dict[str, int] = Field(default_factory=dict)
    all_terminal: bool = False
    all_succeeded: bool = False

class RevOpsCompletionRead(BaseModel):
    """Recomputed artifact-backed deliverable completion."""

    model_config = ConfigDict(extra="forbid")

    requested_fields: tuple[DeliverableFieldKey, ...] = ()
    satisfied_fields: tuple[DeliverableFieldKey, ...] = ()
    missing_fields: tuple[DeliverableFieldKey, ...] = ()
    invalid_fields: tuple[DeliverableFieldKey, ...] = ()
    unproven_fields: tuple[DeliverableFieldKey, ...] = ()
    unresolved_items: tuple[str, ...] = ()
    artifact_complete: bool = False
    assembly_errors: tuple[str, ...] = ()
    complete: bool = False
    observed_row_count: int = 0
    required_row_count: int = 0

class RevOpsMissionDeliverableRead(BaseModel):
    """Final RevOps V1 mission deliverable assembled from current read models."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    kind: Literal["revops_report"] = "revops_report"
    mission_id: uuid.UUID
    objective: str
    # Preserve typed non-prospect artifacts (for example web_page_observation)
    # in the durable read model so a completed mission is inspectable without
    # forcing every job into the prospect-shaped projection.
    artifacts: dict[str, Any] = Field(default_factory=dict)
    prospects: tuple[RevOpsProspectRead, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    approval_state: RevOpsApprovalStateRead
    effects: tuple[RevOpsEffectRead, ...] = ()
    evidence_references: tuple[RevOpsEvidenceReferenceRead, ...] = ()
    task_state: RevOpsTaskStateRead
    completion: RevOpsCompletionRead
    result_semantics: dict[str, Any] = Field(default_factory=dict)
    grants_execution_authority: Literal[False] = False

