"""Review-only proposals for improving tenant knowledge from runtime evidence.

This module intentionally stops at a typed read model.  A proposal is not a
knowledge write, taxonomy mutation, permission grant, handler registration, or
runtime instruction.  Applying one requires a separately owned, reviewed
workflow with provenance and rollback.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.knowledge_change_proposal import KnowledgeChangeProposalRecord
from backend.domain.outcome_review import OutcomeReview
from backend.services.mission_composition.deliverable_runtime_state import DeliverableRuntimeState


class KnowledgeChangeProposal(BaseModel):
    """Evidence-backed suggestion that a human may review later."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    proposal_id: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(min_length=1, max_length=128)
    mission_id: uuid.UUID
    review_id: uuid.UUID
    scope: Literal["tenant_private", "shared_candidate"]
    target_key: str = Field(min_length=1, max_length=256)
    suggested_change: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(min_length=1, max_length=4_000)
    evidence_references: tuple[dict[str, Any], ...] = ()
    source_artifact_ids: tuple[str, ...] = ()
    runtime_reconciliation: Literal["not_available", "aligned", "incomplete", "drifted", "contradictory"] = (
        "not_available"
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: Literal["proposed", "review_required", "accepted", "rejected", "applied", "superseded", "rolled_back"] = (
        "review_required"
    )
    superseded_by_proposal_id: str | None = None
    rollback_of_proposal_id: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    authority_class: Literal["read_model"] = "read_model"
    grants_execution_authority: Literal[False] = False
    generated_at: datetime


class KnowledgeChangeProposalSet(BaseModel):
    """Tenant-scoped proposal projection; never an application command."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    mission_id: uuid.UUID
    proposals: tuple[KnowledgeChangeProposal, ...] = ()
    limitations: tuple[str, ...] = (
        "proposals_are_review_only",
        "shared_candidates_require_explicit_human_review",
        "no_automatic_taxonomy_or_runtime_mutation",
    )
    authority_class: Literal["read_model"] = "read_model"
    grants_execution_authority: Literal[False] = False


def proposal_from_record(record: KnowledgeChangeProposalRecord) -> KnowledgeChangeProposal:
    """Convert a tenant-scoped durable record without widening its authority."""

    scope = cast(Literal["tenant_private", "shared_candidate"], record.scope)
    reconciliation = cast(
        Literal["not_available", "aligned", "incomplete", "drifted", "contradictory"],
        record.runtime_reconciliation,
    )
    lifecycle_status = cast(
        Literal["proposed", "review_required", "accepted", "rejected", "applied", "superseded", "rolled_back"],
        record.status,
    )
    return KnowledgeChangeProposal(
        proposal_id=record.proposal_id,
        tenant_id=record.tenant_id,
        mission_id=record.mission_id,
        review_id=record.review_id,
        scope=scope,
        target_key=record.target_key,
        suggested_change=record.suggested_change,
        rationale=record.rationale,
        evidence_references=tuple(record.evidence_references or []),
        source_artifact_ids=tuple(record.source_artifact_ids or []),
        runtime_reconciliation=reconciliation,
        confidence=record.confidence,
        status=lifecycle_status,
        superseded_by_proposal_id=record.superseded_by_proposal_id,
        rollback_of_proposal_id=record.rollback_of_proposal_id,
        provenance=dict(record.provenance or {}),
        generated_at=record.created_at,
    )


def _proposal_id(*, mission_id: uuid.UUID, review_id: uuid.UUID, target_key: str, suggestion: str) -> str:
    payload = {
        "mission_id": str(mission_id),
        "review_id": str(review_id),
        "target_key": target_key,
        "suggestion": suggestion,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]
    return f"knowledge-change-v1:{digest}"


def _finding_text(
    finding: dict[str, Any],
) -> tuple[str, str, str, float | None, Literal["tenant_private", "shared_candidate"]]:
    target = finding.get("knowledge_key") or finding.get("proposition_key") or finding.get("target_key")
    target_key = str(target) if isinstance(target, str) and target.strip() else "tenant.outcome.review"
    suggestion = finding.get("suggested_change") or finding.get("recommendation") or finding.get("finding")
    suggestion_text = (
        str(suggestion).strip()
        if suggestion is not None
        else "Review the observed outcome and update tenant-private operating knowledge."
    )
    rationale = (
        finding.get("rationale")
        or finding.get("reason")
        or "The outcome review identified a repeatable observation requiring human review."
    )
    rationale_text = str(rationale).strip()
    raw_confidence = finding.get("confidence")
    confidence = float(raw_confidence) if isinstance(raw_confidence, (int, float)) else None
    scope = finding.get("scope")
    proposal_scope = cast(
        Literal["tenant_private", "shared_candidate"],
        scope if scope in {"tenant_private", "shared_candidate"} else "tenant_private",
    )
    return target_key, suggestion_text, rationale_text, confidence, proposal_scope


def build_knowledge_change_proposals(
    *,
    tenant_id: str,
    mission_id: uuid.UUID,
    reviews: list[OutcomeReview],
    runtime_state: DeliverableRuntimeState | None,
    generated_at: datetime | None = None,
) -> KnowledgeChangeProposalSet:
    """Project completed, evidence-backed reviews into review-only proposals.

    Reviews without evidence or without a completed/approved review state are
    deliberately excluded.  Runtime metadata is read only and never changed.
    """

    now = generated_at or datetime.now(UTC)
    raw_reconciliation = (
        runtime_state.runtime_reconciliation.status
        if runtime_state and runtime_state.runtime_reconciliation
        else "not_available"
    )
    reconciliation: Literal["not_available", "aligned", "incomplete", "drifted", "contradictory"] = (
        "not_available" if raw_reconciliation == "not_run" else raw_reconciliation
    )
    proposals: list[KnowledgeChangeProposal] = []
    for review in reviews:
        if str(review.tenant_id) != tenant_id or review.mission_id != mission_id:
            continue
        if review.review_status not in {"completed", "approved"} or review.review_decision == "rejected":
            continue
        if not review.evidence_references:
            continue
        findings = review.structured_findings or [{"finding": review.review_summary}]
        for index, raw_finding in enumerate(findings):
            finding = raw_finding if isinstance(raw_finding, dict) else {"finding": str(raw_finding)}
            target_key, suggestion, rationale, confidence, scope = _finding_text(finding)
            proposal_id = _proposal_id(
                mission_id=mission_id, review_id=review.id, target_key=f"{target_key}:{index}", suggestion=suggestion
            )
            proposals.append(
                KnowledgeChangeProposal(
                    proposal_id=proposal_id,
                    tenant_id=tenant_id,
                    mission_id=mission_id,
                    review_id=review.id,
                    scope=scope,
                    target_key=target_key,
                    suggested_change=suggestion,
                    rationale=rationale,
                    evidence_references=tuple(review.evidence_references),
                    source_artifact_ids=tuple(
                        str(ref.get("artifact_id"))
                        for ref in review.evidence_references
                        if isinstance(ref, dict) and isinstance(ref.get("artifact_id"), str)
                    ),
                    runtime_reconciliation=reconciliation,
                    confidence=confidence if confidence is not None else review.confidence,
                    generated_at=now,
                )
            )
    return KnowledgeChangeProposalSet(mission_id=mission_id, proposals=tuple(proposals))
