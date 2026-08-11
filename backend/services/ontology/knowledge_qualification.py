"""Pure deterministic qualification of Experience pattern candidates.

This layer consumes Experience-owned semantics and recurrence judgments. It does
not reconstruct owner meaning, infer causality, persist knowledge, create policy,
or alter runtime behavior.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from backend.services.ontology.commercial_state import KpiSemanticSignature
from backend.services.ontology.experience_intelligence import (
    ExperiencePatternCandidate,
    GoalSemanticBasis,
    InterventionSemanticBasis,
    RecurrenceStrength,
)
from backend.services.ontology.types import BusinessObjectSemanticSignature

KNOWLEDGE_QUALIFICATION_ALGORITHM = "knowledge_qualification_v1"


class KnowledgeQualificationStatus(StrEnum):
    INSUFFICIENT = "insufficient"
    PROVISIONAL = "provisional"
    QUALIFIED = "qualified"
    CONTESTED = "contested"
    INVALIDATED = "invalidated"


class KnowledgeRelationshipType(StrEnum):
    ASSOCIATED_WITH_FAVORABLE_OUTCOME = "associated_with_favorable_outcome"


class QualificationGateDecision(StrEnum):
    PASS = "pass"
    CAP_PROVISIONAL = "cap_provisional"
    FAIL = "fail"


class QualificationGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: QualificationGateDecision
    reason_codes: tuple[str, ...] = ()


class KnowledgeQualificationGates(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    semantic_identity_gate: QualificationGateResult
    intervention_authority_gate: QualificationGateResult
    goal_authority_gate: QualificationGateResult
    recurrence_gate: QualificationGateResult
    independent_support_gate: QualificationGateResult
    contradiction_gate: QualificationGateResult
    scope_gate: QualificationGateResult
    temporal_provenance_gate: QualificationGateResult


class KnowledgeProposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    proposition_key: str
    subject_semantic_signatures: tuple[BusinessObjectSemanticSignature, ...]
    intervention_key: str
    objective_key: str | None = None
    kpi_semantic_signatures: tuple[KpiSemanticSignature, ...] = ()
    relationship_type: KnowledgeRelationshipType
    scope_conditions: tuple[str, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()


class KnowledgeEvidenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_candidate_id: str
    recurrence_strength: RecurrenceStrength
    independent_support_count: int
    dependent_support_count: int
    strong_independent_contradiction_count: int
    limited_support_count: int
    limited_contradiction_count: int
    dependent_contradiction_count: int
    ambiguous_unit_count: int
    supporting_episode_ids: tuple[str, ...] = ()
    contradicting_episode_ids: tuple[str, ...] = ()
    neutral_episode_ids: tuple[str, ...] = ()
    ambiguous_episode_ids: tuple[str, ...] = ()
    excluded_episode_ids: tuple[str, ...] = ()
    dependent_episode_groups: tuple[tuple[str, ...], ...] = ()
    earliest_evaluated_at: datetime | None = None
    latest_evaluated_at: datetime | None = None
    experience_algorithm: str


class QualifiedKnowledgeArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    knowledge_id: str
    proposition: KnowledgeProposition
    source_candidate_id: str
    qualification_id: str
    qualified_through_evaluated_at: datetime | None
    algorithm: str = KNOWLEDGE_QUALIFICATION_ALGORITHM
    is_knowledge: Literal[True] = True
    is_policy: Literal[False] = False
    is_persisted: Literal[False] = False


class KnowledgeQualificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    qualification_id: str
    source_candidate_id: str
    proposition: KnowledgeProposition | None
    status: KnowledgeQualificationStatus
    gates: KnowledgeQualificationGates
    evidence_summary: KnowledgeEvidenceSummary
    reason_codes: tuple[str, ...] = ()
    epistemic_limits: tuple[str, ...] = ()
    qualified_knowledge: QualifiedKnowledgeArtifact | None = None
    algorithm: str = KNOWLEDGE_QUALIFICATION_ALGORITHM
    is_policy: Literal[False] = False

    @model_validator(mode="after")
    def validate_artifact_boundary(self) -> KnowledgeQualificationResult:
        if (self.status == KnowledgeQualificationStatus.QUALIFIED) != (self.qualified_knowledge is not None):
            raise ValueError("only qualified results may contain qualified knowledge")
        return self


def _canonical(value: object) -> object:
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        items = [_canonical(item) for item in value]
        return sorted(items, key=lambda item: _stable_json(item))
    return value


def _stable_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _identity(prefix: str, payload: object) -> str:
    digest = hashlib.sha256(_stable_json(_canonical(payload)).encode()).hexdigest()
    return f"{prefix}:{digest}"


def _gate(decision: QualificationGateDecision, *codes: str) -> QualificationGateResult:
    return QualificationGateResult(decision=decision, reason_codes=tuple(sorted(set(codes))))


def _evidence_summary(candidate: ExperiencePatternCandidate) -> KnowledgeEvidenceSummary:
    recurrence = candidate.recurrence
    return KnowledgeEvidenceSummary(
        source_candidate_id=candidate.candidate_id,
        recurrence_strength=recurrence.strength,
        independent_support_count=recurrence.independent_support_count,
        dependent_support_count=recurrence.dependent_support_count,
        strong_independent_contradiction_count=recurrence.strong_independent_contradiction_count,
        limited_support_count=recurrence.limited_support_count,
        limited_contradiction_count=recurrence.limited_contradiction_count,
        dependent_contradiction_count=recurrence.dependent_contradiction_count,
        ambiguous_unit_count=recurrence.ambiguous_unit_count,
        supporting_episode_ids=tuple(sorted(set(candidate.supporting_episode_ids))),
        contradicting_episode_ids=tuple(sorted(set(candidate.contradicting_episode_ids))),
        neutral_episode_ids=tuple(sorted(set(candidate.neutral_episode_ids))),
        ambiguous_episode_ids=tuple(sorted(set(candidate.ambiguous_episode_ids))),
        excluded_episode_ids=tuple(sorted(set(candidate.excluded_episode_ids))),
        dependent_episode_groups=tuple(
            sorted({tuple(sorted(set(group))) for group in candidate.dependent_episode_groups})
        ),
        earliest_evaluated_at=candidate.earliest_evaluated_at,
        latest_evaluated_at=candidate.latest_evaluated_at,
        experience_algorithm=candidate.algorithm,
    )


def qualify_pattern_knowledge(candidate: ExperiencePatternCandidate) -> KnowledgeQualificationResult:
    """Qualify a candidate without I/O, clocks, rescoring, or semantic inference."""

    qualification_id = _identity(
        "knowledge-qualification-v1",
        {"algorithm": KNOWLEDGE_QUALIFICATION_ALGORITHM, "candidate": candidate.model_dump(mode="json")},
    )
    context = candidate.semantic_context
    semantic_codes: list[str] = []
    if context is None:
        semantic_codes.append("missing_typed_semantic_context")
    else:
        if not context.subject_semantic_signatures:
            semantic_codes.append("missing_subject_semantics")
        if not context.intervention_key:
            semantic_codes.append("missing_intervention_semantics")
        if not context.objective_key and not context.common_kpi_semantic_signatures:
            semantic_codes.append("portable_goal_semantics_absent")
        if (
            not context.intervention_semantic_bases
            or not context.goal_semantic_bases
            or context.intervention_key != candidate.recommendation_class
            or context.scope_conditions != candidate.common_scope_conditions
            or context.invalidation_conditions != candidate.invalidation_conditions
        ):
            semantic_codes.append("semantic_context_structurally_contradictory")
    semantic_gate = _gate(
        QualificationGateDecision.FAIL if semantic_codes else QualificationGateDecision.PASS,
        *(semantic_codes or ["typed_semantic_identity_present"]),
    )

    if context is None or not context.intervention_semantic_bases:
        intervention_gate = _gate(QualificationGateDecision.FAIL, "intervention_authority_absent")
    elif set(context.intervention_semantic_bases) == {InterventionSemanticBasis.DECISION_OWNER}:
        intervention_gate = _gate(QualificationGateDecision.PASS, "decision_owner_intervention")
    else:
        intervention_gate = _gate(QualificationGateDecision.CAP_PROVISIONAL, "legacy_intervention_semantics_present")

    goal_bases = set(context.goal_semantic_bases) if context else set()
    if not goal_bases or goal_bases == {GoalSemanticBasis.EXACT_GOAL_INSTANCE_FALLBACK}:
        goal_gate = _gate(QualificationGateDecision.FAIL, "exact_goal_instance_not_portable")
    elif context and context.objective_key and goal_bases == {GoalSemanticBasis.OWNER_EXPLICIT_OBJECTIVE}:
        goal_gate = _gate(QualificationGateDecision.PASS, "owner_explicit_objective_semantics")
    else:
        goal_gate = _gate(QualificationGateDecision.CAP_PROVISIONAL, "conservative_goal_semantic_authority")

    recurrence_decisions = {
        RecurrenceStrength.WEAK: QualificationGateDecision.FAIL,
        RecurrenceStrength.EMERGING: QualificationGateDecision.CAP_PROVISIONAL,
        RecurrenceStrength.SUPPORTED: QualificationGateDecision.PASS,
        RecurrenceStrength.CONTESTED: QualificationGateDecision.FAIL,
        RecurrenceStrength.INVALIDATED: QualificationGateDecision.FAIL,
    }
    recurrence_gate = _gate(
        recurrence_decisions[candidate.recurrence.strength], f"recurrence_{candidate.recurrence.strength.value}"
    )
    support_gate = _gate(
        QualificationGateDecision.PASS
        if candidate.recurrence.independent_support_count >= 3
        else QualificationGateDecision.CAP_PROVISIONAL,
        "independent_support_threshold_met"
        if candidate.recurrence.independent_support_count >= 3
        else "fewer_than_three_independent_support_units",
    )
    malformed_recurrence = (
        candidate.recurrence.strength == RecurrenceStrength.SUPPORTED
        and candidate.recurrence.strong_independent_contradiction_count > 0
    )
    contradiction_gate = _gate(
        QualificationGateDecision.FAIL if malformed_recurrence else QualificationGateDecision.PASS,
        "recurrence_contract_inconsistent" if malformed_recurrence else "no_upstream_contract_contradiction",
    )
    if candidate.conflicting_scope_conditions:
        scope_gate = _gate(QualificationGateDecision.FAIL, "conflicting_scope_conditions")
    elif context is None or not context.scope_conditions:
        scope_gate = _gate(QualificationGateDecision.CAP_PROVISIONAL, "unbounded_scope")
    else:
        scope_gate = _gate(QualificationGateDecision.PASS, "bounded_common_scope")
    temporal_invalid = bool(
        candidate.earliest_evaluated_at
        and candidate.latest_evaluated_at
        and candidate.earliest_evaluated_at > candidate.latest_evaluated_at
    )
    temporal_gate = _gate(
        QualificationGateDecision.FAIL if temporal_invalid else QualificationGateDecision.PASS,
        "invalid_evaluation_time_order" if temporal_invalid else "evaluation_time_order_valid",
    )
    gates = KnowledgeQualificationGates(
        semantic_identity_gate=semantic_gate,
        intervention_authority_gate=intervention_gate,
        goal_authority_gate=goal_gate,
        recurrence_gate=recurrence_gate,
        independent_support_gate=support_gate,
        contradiction_gate=contradiction_gate,
        scope_gate=scope_gate,
        temporal_provenance_gate=temporal_gate,
    )

    proposition = None
    if context and semantic_gate.decision != QualificationGateDecision.FAIL:
        proposition_payload = {
            "subjects": [item.model_dump(mode="json") for item in context.subject_semantic_signatures],
            "intervention_key": context.intervention_key,
            "objective_key": context.objective_key,
            "kpis": [item.model_dump(mode="json") for item in context.common_kpi_semantic_signatures],
            "relationship_type": KnowledgeRelationshipType.ASSOCIATED_WITH_FAVORABLE_OUTCOME.value,
            "scope": list(context.scope_conditions),
            "invalidation": list(context.invalidation_conditions),
        }
        proposition = KnowledgeProposition(
            proposition_key=_identity("knowledge-proposition-v1", proposition_payload),
            subject_semantic_signatures=tuple(
                sorted(set(context.subject_semantic_signatures), key=lambda item: item.object_type.value)
            ),
            intervention_key=context.intervention_key,
            objective_key=context.objective_key,
            kpi_semantic_signatures=tuple(
                sorted(
                    set(context.common_kpi_semantic_signatures),
                    key=lambda item: (item.metric, item.direction.value, item.normalized_unit or ""),
                )
            ),
            relationship_type=KnowledgeRelationshipType.ASSOCIATED_WITH_FAVORABLE_OUTCOME,
            scope_conditions=tuple(sorted(set(context.scope_conditions))),
            invalidation_conditions=tuple(sorted(set(context.invalidation_conditions))),
        )

    gate_names = KnowledgeQualificationGates.model_fields
    decisions = [getattr(gates, name).decision for name in gate_names]
    if candidate.recurrence.strength == RecurrenceStrength.INVALIDATED:
        status = KnowledgeQualificationStatus.INVALIDATED
    elif candidate.recurrence.strength == RecurrenceStrength.CONTESTED:
        status = KnowledgeQualificationStatus.CONTESTED
    elif QualificationGateDecision.FAIL in decisions:
        status = KnowledgeQualificationStatus.INSUFFICIENT
    elif QualificationGateDecision.CAP_PROVISIONAL in decisions:
        status = KnowledgeQualificationStatus.PROVISIONAL
    else:
        status = KnowledgeQualificationStatus.QUALIFIED

    limits = {
        "non_causal_knowledge",
        "qualification_not_persistence",
        "qualification_not_policy",
        "qualification_not_planner_instruction",
        "qualification_not_behavior_change",
        "evaluation_time_not_observation_time",
    }
    if context:
        if InterventionSemanticBasis.LEGACY_EXPERIENCE_FALLBACK in context.intervention_semantic_bases:
            limits.add("legacy_intervention_semantics_present")
        if goal_bases & {GoalSemanticBasis.INHERITED_EXPLICIT_OBJECTIVE, GoalSemanticBasis.INHERITED_KPI_ONLY}:
            limits.add("inherited_goal_semantics_present")
        if goal_bases & {GoalSemanticBasis.OWNER_KPI_ONLY, GoalSemanticBasis.INHERITED_KPI_ONLY}:
            limits.add("kpi_only_goal_semantics")
        if not context.scope_conditions:
            limits.add("unbounded_scope")
    if candidate.recurrence.limited_contradiction_count or candidate.recurrence.dependent_contradiction_count:
        limits.add("limited_counterevidence_present")
    reason_codes = tuple(sorted({code for name in gate_names for code in getattr(gates, name).reason_codes}))
    artifact = None
    if status == KnowledgeQualificationStatus.QUALIFIED and proposition:
        knowledge_id = _identity(
            "qualified-knowledge-v1",
            {
                "qualification_id": qualification_id,
                "proposition_key": proposition.proposition_key,
                "algorithm": KNOWLEDGE_QUALIFICATION_ALGORITHM,
            },
        )
        artifact = QualifiedKnowledgeArtifact(
            knowledge_id=knowledge_id,
            proposition=proposition,
            source_candidate_id=candidate.candidate_id,
            qualification_id=qualification_id,
            qualified_through_evaluated_at=candidate.latest_evaluated_at,
        )
    return KnowledgeQualificationResult(
        qualification_id=qualification_id,
        source_candidate_id=candidate.candidate_id,
        proposition=proposition,
        status=status,
        gates=gates,
        evidence_summary=_evidence_summary(candidate),
        reason_codes=reason_codes,
        epistemic_limits=tuple(sorted(limits)),
        qualified_knowledge=artifact,
    )
