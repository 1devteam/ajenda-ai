"""Versioned interpretation-readiness policy (separate from composition/runtime readiness)."""

from __future__ import annotations

from dataclasses import dataclass

from backend.services.mission_composition.contracts import MissionIntent
from backend.services.mission_composition.deliverable_coverage import reconcile_deliverable_coverage

READINESS_POLICY_VERSION = "3"


@dataclass(frozen=True, slots=True)
class InterpretationReadinessResult:
    ready: bool
    policy_version: str
    minimum_coverage: float
    minimum_outcome_confidence: float
    reasons: tuple[str, ...]


def evaluate_interpretation_readiness(intent: MissionIntent) -> InterpretationReadinessResult:
    """Deterministic gate: did Ajenda understand the mission?"""

    intent = reconcile_deliverable_coverage(intent)
    reasons: list[str] = []
    min_coverage = 0.99
    min_outcome_conf = 0.7
    external_risk = any(
        outcome
        in {
            "send_outreach",
            "update_crm",
            "publish_content",
            "read_email",
            "read_crm",
            "query_salesforce",
            "read_calendar",
            "read_linkedin",
            "read_github",
            "read_contacts",
        }
        for outcome in intent.requested_outcomes
    )
    if external_risk:
        min_coverage = 1.0
        min_outcome_conf = 0.85

    if not intent.requested_outcomes and not intent.unsupported_outcomes:
        reasons.append("no_canonical_or_unsupported_outcome")
    if intent.coverage_score < min_coverage:
        reasons.append(f"coverage_below_threshold:{intent.coverage_score:.2f}<{min_coverage}")
    if intent.unmatched_material_units:
        high_risk = [u for u in intent.unmatched_material_units if u.risk in {"high", "critical"}]
        if high_risk:
            reasons.append("unmatched_high_risk_semantic_units")
        elif intent.coverage_score < 1.0:
            reasons.append("unmatched_material_semantic_units")
    if intent.contradictions:
        unresolved = [c for c in intent.contradictions if c.resolution_status == "unresolved"]
        if unresolved:
            reasons.append("unresolved_contradictions")
    if intent.ambiguity:
        reasons.append("restatement_required")
    # minimum_field_confidence is computed from non-default evidence only.
    if intent.minimum_field_confidence is not None and intent.minimum_field_confidence < min_outcome_conf:
        reasons.append(f"field_confidence_below_threshold:{intent.minimum_field_confidence:.2f}")
    if intent.send_policy.mode == "unknown" and "send_outreach" in intent.requested_outcomes:
        reasons.append("send_policy_unresolved")

    ready = not reasons and bool(intent.requested_outcomes)
    return InterpretationReadinessResult(
        ready=ready,
        policy_version=READINESS_POLICY_VERSION,
        minimum_coverage=min_coverage,
        minimum_outcome_confidence=min_outcome_conf,
        reasons=tuple(reasons),
    )
