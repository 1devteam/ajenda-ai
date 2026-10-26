"""Admission of Knowledge-owned runtime evidence into a need assessment.

This adapter never interprets Knowledge as policy or requalifies a proposition.
It proves the unique canonical action projection, then checks that the
Decision-owned input and Knowledge query address this precise need revision.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.orm import Session

from backend.repositories.evidence_repository import EvidenceRepository
from backend.services.business_understanding.subject_identity import canonical_subject_keys
from backend.services.knowledge.knowledge_decision_support import KnowledgeDecisionSupportResult
from backend.services.ontology.commercial_state import Goal, Kpi, goal_semantic_signature
from backend.services.ontology.types import BusinessObjectRef, business_object_semantic_signature
from backend.services.tools.evidence_bridge import require_canonical_tool_action_evidence
from backend.services.tools.schemas import DecisionRecommendInput


def resolve_verified_assessment_knowledge_support(
    *,
    session: Session,
    tenant_id: str,
    evidence_id: uuid.UUID,
    need_subjects: Sequence[BusinessObjectRef | dict[str, object]],
    goal: Goal,
    kpis: tuple[Kpi, ...],
    candidate_response_keys: tuple[str, ...],
    assessed_at: datetime,
) -> KnowledgeDecisionSupportResult:
    """Read canonical tenant evidence and prohibit cross-need or future reuse."""

    record = EvidenceRepository(session).get_for_tenant(tenant_id=tenant_id, evidence_id=evidence_id)
    if record is None:
        raise ValueError("assessment knowledge evidence is inaccessible for tenant")
    if record.evidence_source != "knowledge_decision_support":
        raise ValueError("assessment knowledge evidence has an incorrect owner")
    require_canonical_tool_action_evidence(
        session=session,
        record=record,
        expected_action="knowledge.inform_decision",
        expected_role="decision_recommendation_result",
    )
    output = record.structured_payload
    if not isinstance(output, dict) or not isinstance(output.get("support"), dict):
        raise ValueError("assessment knowledge evidence has no canonical support result")
    try:
        support = KnowledgeDecisionSupportResult.model_validate(output["support"])
        scoring_input = DecisionRecommendInput.model_validate(output["scoring_decision_input"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("assessment knowledge evidence has an invalid owner payload") from exc

    if support.evaluated_at > assessed_at or record.created_at > assessed_at:
        raise ValueError("future knowledge evidence cannot inform an earlier need assessment")
    expected_subjects = canonical_subject_keys(need_subjects)
    if (
        not expected_subjects
        or canonical_subject_keys(scoring_input.subject_refs) != expected_subjects
        or canonical_subject_keys(goal.subject_refs) != expected_subjects
    ):
        raise ValueError("assessment knowledge support belongs to different subject instances")
    query = support.applicability.retrieval.query
    expected_goal = goal_semantic_signature(goal, kpis)
    if (
        scoring_input.goal_ref is None
        or scoring_input.goal_ref.goal_id != goal.goal_id
        or goal_semantic_signature(scoring_input.goal_ref, scoring_input.kpis) != expected_goal
        or query.goal_semantic_signature != expected_goal
    ):
        raise ValueError("assessment knowledge support goal semantics disagree")
    subject_semantics = {business_object_semantic_signature(ref) for ref in scoring_input.subject_refs}
    if set(query.subject_semantic_signatures) != subject_semantics:
        raise ValueError("assessment knowledge query has different subject semantics")

    option_ids = [option.option_id for option in scoring_input.options]
    if (
        len(option_ids) != len(set(option_ids))
        or set(option_ids) != set(candidate_response_keys)
        or len(candidate_response_keys) != len(set(candidate_response_keys))
        or any(
            influence.option_id not in option_ids
            or influence.decision_id != support.decision_id
            or influence.evaluated_at > assessed_at
            for influence in support.influences
        )
    ):
        raise ValueError("assessment knowledge support is not bound to the assessed responses")
    if scoring_input.context.get("knowledge_decision_support", {}).get("support_id") != support.support_id:
        raise ValueError("assessment knowledge support identity contradicts Decision input")
    return support
