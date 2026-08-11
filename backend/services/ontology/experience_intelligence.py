"""Experience Intelligence Slice 1 — deterministic recurrence eligibility.

This module compares DecisionLearningSignal observations without promoting them
to knowledge, policy, memory, behavior changes, or action execution. The unit of
recurrence is an eligible, semantically comparable, dependence-resolved evidence
unit — not a raw episode and not a pairwise comparison.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.services.ontology.decision_feedback import (
    DecisionEffectivenessStatus,
    DecisionLearningSignal,
    ExecutionFidelity,
    LearningSignalStrength,
)
from backend.services.ontology.observation_attribution import ObservationTimeProvenance
from backend.services.ontology.outcome import AttributionAssessment

EXPERIENCE_INTELLIGENCE_SCHEMA_VERSION = 1
EXPERIENCE_INTELLIGENCE_ALGORITHM = "experience_equivalence_recurrence_v1"


class ComparabilityStatus(StrEnum):
    COMPARABLE = "comparable"
    PARTIALLY_COMPARABLE = "partially_comparable"
    INCOMPATIBLE = "incompatible"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class IndependenceStatus(StrEnum):
    INDEPENDENT = "independent"
    PARTIALLY_INDEPENDENT = "partially_independent"
    DEPENDENT = "dependent"
    INDETERMINATE = "indeterminate"


class RecurrenceStrength(StrEnum):
    WEAK = "weak"
    EMERGING = "emerging"
    SUPPORTED = "supported"
    CONTESTED = "contested"
    INVALIDATED = "invalidated"


class EvidenceContributionTier(StrEnum):
    STRONG = "strong"
    LIMITED = "limited"
    INELIGIBLE = "ineligible"


class EvidenceUnitDirection(StrEnum):
    SUPPORT = "support"
    CONTRADICTION = "contradiction"
    NEUTRAL = "neutral"
    AMBIGUOUS = "ambiguous"


class ExperienceEpisodeInput(BaseModel):
    """One episode plus explicit V1 recurrence metadata.

    recommendation_class is accepted transitional V1 intervention metadata.
    objective_dimensions are preserved as caller context only; they do not earn
    cross-goal semantic equivalence in this slice.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_id: str = Field(min_length=1, max_length=160)
    signal: DecisionLearningSignal
    recommendation_class: str | None = Field(default=None, max_length=160)
    objective_dimensions: tuple[str, ...] = ()
    attribution_evidence_ids: tuple[str, ...] = ()
    observation_time_provenance: ObservationTimeProvenance = ObservationTimeProvenance.UNKNOWN
    lineage_ids: tuple[str, ...] = ()


class ExperienceContextSignature(BaseModel):
    """Deterministic signature keeping exact identity separate from semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    episode_id: str
    exact_signal_id: str
    exact_decision_id: str
    exact_subject_refs: tuple[str, ...] = ()
    exact_goal_id: str | None = None
    semantic_subject_types: tuple[str, ...] = ()
    recommendation_class: str | None = None
    objective_dimensions: tuple[str, ...] = ()
    learning_signal_algorithm: str
    effective_dimensions: tuple[str, ...] = ()
    ineffective_dimensions: tuple[str, ...] = ()
    attribution_assessment: AttributionAssessment
    observation_time_provenance: ObservationTimeProvenance
    execution_fidelity: ExecutionFidelity
    learning_signal_strength: LearningSignalStrength
    scope_conditions: tuple[str, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()
    supporting_evidence_ids: tuple[str, ...] = ()
    lineage_ids: tuple[str, ...] = ()


class ExperienceComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    left_episode_id: str
    right_episode_id: str
    comparability: ComparabilityStatus
    independence: IndependenceStatus
    reason_codes: tuple[str, ...] = ()


class RecurrenceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strength: RecurrenceStrength
    comparability: ComparabilityStatus
    independence: IndependenceStatus
    independent_support_count: int
    dependent_support_count: int
    strong_independent_contradiction_count: int
    limited_support_count: int = 0
    limited_contradiction_count: int = 0
    dependent_contradiction_count: int = 0
    ambiguous_unit_count: int = 0
    evidence_limitation: str | None = None
    reason_codes: tuple[str, ...] = ()


class ExperiencePatternCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    candidate_id: str
    partition_key: str
    recommendation_class: str
    subject_types: tuple[str, ...]
    goal_id: str
    objective_dimensions: tuple[str, ...] = ()
    supporting_episode_ids: tuple[str, ...] = ()
    contradicting_episode_ids: tuple[str, ...] = ()
    neutral_episode_ids: tuple[str, ...] = ()
    ambiguous_episode_ids: tuple[str, ...] = ()
    excluded_episode_ids: tuple[str, ...] = ()
    dependent_episode_groups: tuple[tuple[str, ...], ...] = ()
    common_scope_conditions: tuple[str, ...] = ()
    conflicting_scope_conditions: tuple[str, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()
    earliest_evaluated_at: datetime | None = None
    latest_evaluated_at: datetime | None = None
    recurrence: RecurrenceAssessment
    explanation_codes: tuple[str, ...] = ()
    algorithm: str = EXPERIENCE_INTELLIGENCE_ALGORITHM
    is_knowledge: Literal[False] = False
    is_policy: Literal[False] = False

    @model_validator(mode="after")
    def enforce_safety_flags(self) -> ExperiencePatternCandidate:
        if self.is_knowledge is not False or self.is_policy is not False:
            raise ValueError("experience pattern candidates cannot be knowledge or policy")
        return self


class ExperienceIntelligenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    signatures: tuple[ExperienceContextSignature, ...] = ()
    comparisons: tuple[ExperienceComparison, ...] = ()
    pattern_candidates: tuple[ExperiencePatternCandidate, ...] = ()
    excluded_episode_ids: tuple[str, ...] = ()
    unclassified_episode_ids: tuple[str, ...] = ()
    dependent_episode_groups: tuple[tuple[str, ...], ...] = ()
    partition_explanations: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    episode_explanations: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    epistemic_limits: tuple[str, ...] = (
        "candidate_only_not_knowledge",
        "candidate_only_not_policy",
        "non_causal_recurrence_assessment",
        "no_memory_or_behavior_change",
        "objective_dimensions_are_caller_context_not_goal_semantics_v1",
        "recommendation_class_is_transitional_v1_metadata",
    )
    algorithm: str = EXPERIENCE_INTELLIGENCE_ALGORITHM


@dataclass(frozen=True)
class _Eligibility:
    episode_id: str
    tier: EvidenceContributionTier
    direction: EvidenceUnitDirection
    reason_codes: tuple[str, ...]
    partition_key: str | None
    unclassified: bool = False
    excluded: bool = False


@dataclass(frozen=True)
class _EvidenceUnit:
    episode_ids: tuple[str, ...]
    direction: EvidenceUnitDirection
    tier: EvidenceContributionTier
    independence: IndependenceStatus
    reason_codes: tuple[str, ...]


class _UnionFind:
    def __init__(self, ids: list[str]) -> None:
        self.parent = {item: item for item in ids}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        lroot = self.find(left)
        rroot = self.find(right)
        if lroot == rroot:
            return
        root, child = sorted((lroot, rroot))
        self.parent[child] = root


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().casefold()
    return stripped or None


def _canonical_semantic_values(items: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({i.strip().casefold() for i in items if i and i.strip()}))


def _canonical_identifiers(items: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Canonicalize opaque IDs without changing their identity semantics."""

    return tuple(sorted({i.strip() for i in items if i and i.strip()}))


def _subject_ref_key(ref: object) -> str:
    object_type = getattr(getattr(ref, "object_type", None), "value", getattr(ref, "object_type", ""))
    object_id = getattr(ref, "object_id", "")
    return f"{str(object_type).strip().casefold()}:{str(object_id).strip()}"


def derive_context_signature(
    episode: ExperienceEpisodeInput,
) -> ExperienceContextSignature:
    signal = episode.signal
    return ExperienceContextSignature(
        episode_id=episode.episode_id,
        exact_signal_id=signal.signal_id,
        exact_decision_id=signal.decision_id,
        exact_subject_refs=tuple(sorted({_subject_ref_key(ref) for ref in signal.subject_refs})),
        exact_goal_id=signal.goal_id.strip() if signal.goal_id and signal.goal_id.strip() else None,
        semantic_subject_types=_canonical_semantic_values(tuple(ref.object_type.value for ref in signal.subject_refs)),
        recommendation_class=_norm(episode.recommendation_class),
        objective_dimensions=_canonical_semantic_values(episode.objective_dimensions),
        learning_signal_algorithm=signal.algorithm,
        effective_dimensions=_canonical_semantic_values(tuple(signal.effective_dimensions)),
        ineffective_dimensions=_canonical_semantic_values(tuple(signal.ineffective_dimensions)),
        attribution_assessment=signal.attribution_strength,
        observation_time_provenance=episode.observation_time_provenance,
        execution_fidelity=signal.execution_fidelity,
        learning_signal_strength=signal.signal_strength,
        scope_conditions=_canonical_semantic_values(tuple(signal.scope_conditions)),
        invalidation_conditions=_canonical_semantic_values(tuple(signal.invalidation_conditions)),
        supporting_evidence_ids=_canonical_identifiers(
            tuple(signal.supporting_evidence_ids) + episode.attribution_evidence_ids
        ),
        lineage_ids=_canonical_identifiers(episode.lineage_ids),
    )


def _partition_payload(sig: ExperienceContextSignature) -> dict[str, object] | None:
    if not sig.recommendation_class or sig.recommendation_class == "unknown":
        return None
    if not sig.semantic_subject_types:
        return None
    if sig.exact_goal_id is None:
        return None
    return {
        "goal_id": sig.exact_goal_id,
        "recommendation_class": sig.recommendation_class,
        "scope_conditions": list(sig.scope_conditions),
        "subject_types": list(sig.semantic_subject_types),
    }


def _stable_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _stable_key(payload: dict[str, object]) -> str:
    digest = hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()[:16]
    return f"experience-partition-v1:{digest}"


def _partition_key(sig: ExperienceContextSignature) -> str | None:
    payload = _partition_payload(sig)
    if payload is None:
        return None
    return _stable_key(payload)


def _compare(a: ExperienceContextSignature, b: ExperienceContextSignature) -> ExperienceComparison:
    left, right = sorted((a, b), key=lambda sig: sig.episode_id)
    codes: list[str] = []
    if not left.recommendation_class or not right.recommendation_class:
        codes.append("missing_recommendation_class_unclassified")
        comp = ComparabilityStatus.INSUFFICIENT_CONTEXT
    elif left.recommendation_class == "unknown" or right.recommendation_class == "unknown":
        codes.append("unknown_recommendation_class_unclassified")
        comp = ComparabilityStatus.INSUFFICIENT_CONTEXT
    elif left.recommendation_class != right.recommendation_class:
        codes.append("different_recommendation_class_partition")
        comp = ComparabilityStatus.INCOMPATIBLE
    elif left.semantic_subject_types != right.semantic_subject_types:
        codes.append("different_subject_type")
        comp = ComparabilityStatus.INCOMPATIBLE
    elif left.exact_goal_id is None or right.exact_goal_id is None:
        codes.append("goal_semantics_insufficient")
        comp = ComparabilityStatus.INSUFFICIENT_CONTEXT
    elif left.exact_goal_id != right.exact_goal_id:
        codes.append("different_goal_id_without_owned_semantic_equivalence")
        comp = ComparabilityStatus.INCOMPATIBLE
    elif left.scope_conditions != right.scope_conditions:
        codes.append("different_scope_conditions_partition")
        comp = ComparabilityStatus.PARTIALLY_COMPARABLE
    else:
        codes.append("same_semantic_partition")
        comp = ComparabilityStatus.COMPARABLE
    indep, indep_codes = _pair_independence(left, right)
    return ExperienceComparison(
        left_episode_id=left.episode_id,
        right_episode_id=right.episode_id,
        comparability=comp,
        independence=indep,
        reason_codes=tuple(codes + indep_codes),
    )


def _pair_independence(
    a: ExperienceContextSignature, b: ExperienceContextSignature
) -> tuple[IndependenceStatus, list[str]]:
    codes: list[str] = []
    hard = False
    partial = False
    if a.exact_signal_id == b.exact_signal_id:
        hard = True
        codes.append("duplicate_signal_id")
    if a.exact_decision_id == b.exact_decision_id:
        hard = True
        codes.append("duplicate_decision_id")
    if set(a.lineage_ids) & set(b.lineage_ids):
        hard = True
        codes.append("reused_lineage")
    if set(a.supporting_evidence_ids) & set(b.supporting_evidence_ids):
        partial = True
        codes.append("overlapping_evidence_ids")
    if set(a.exact_subject_refs) & set(b.exact_subject_refs):
        partial = True
        codes.append("same_subject_instance_correlation")
    if hard:
        return IndependenceStatus.DEPENDENT, codes
    if partial:
        return IndependenceStatus.PARTIALLY_INDEPENDENT, codes
    if not a.supporting_evidence_ids or not b.supporting_evidence_ids:
        return IndependenceStatus.INDETERMINATE, [
            *codes,
            "independence_evidence_insufficient",
        ]
    return IndependenceStatus.INDEPENDENT, [*codes, "no_dependence_signal_detected"]


def _base_direction(signal: DecisionLearningSignal) -> EvidenceUnitDirection:
    if signal.effectiveness.status in {
        DecisionEffectivenessStatus.HIGHLY_EFFECTIVE,
        DecisionEffectivenessStatus.EFFECTIVE,
        DecisionEffectivenessStatus.PARTIALLY_EFFECTIVE,
    }:
        return EvidenceUnitDirection.SUPPORT
    if signal.effectiveness.status in {
        DecisionEffectivenessStatus.INEFFECTIVE,
        DecisionEffectivenessStatus.COUNTERPRODUCTIVE,
    }:
        return EvidenceUnitDirection.CONTRADICTION
    return EvidenceUnitDirection.NEUTRAL


def _eligibility(
    *,
    sig: ExperienceContextSignature,
    signal: DecisionLearningSignal,
    partition_key: str | None,
    active_scope_conditions: tuple[str, ...],
) -> _Eligibility:
    codes: list[str] = []
    if partition_key is None:
        if not sig.recommendation_class:
            codes.append("missing_recommendation_class")
        elif sig.recommendation_class == "unknown":
            codes.append("unknown_recommendation_class_not_semantic")
        if sig.exact_goal_id is None:
            codes.append("missing_goal_id_insufficient_goal_semantics")
        if not sig.semantic_subject_types:
            codes.append("missing_subject_type_semantics")
        return _Eligibility(
            episode_id=sig.episode_id,
            tier=EvidenceContributionTier.INELIGIBLE,
            direction=EvidenceUnitDirection.NEUTRAL,
            reason_codes=tuple(codes or ["semantic_context_insufficient"]),
            partition_key=None,
            unclassified=True,
        )

    direction = _base_direction(signal)
    tier = EvidenceContributionTier.STRONG
    if sig.invalidation_conditions and set(sig.invalidation_conditions) & set(active_scope_conditions):
        codes.append("active_scope_matches_invalidation_condition")
        return _Eligibility(
            episode_id=sig.episode_id,
            tier=EvidenceContributionTier.INELIGIBLE,
            direction=EvidenceUnitDirection.NEUTRAL,
            reason_codes=tuple(codes),
            partition_key=partition_key,
            excluded=True,
        )

    if sig.execution_fidelity == ExecutionFidelity.NOT_EXECUTED:
        codes.append("intervention_not_executed_not_counterexample")
        return _Eligibility(
            episode_id=sig.episode_id,
            tier=EvidenceContributionTier.INELIGIBLE,
            direction=EvidenceUnitDirection.NEUTRAL,
            reason_codes=tuple(codes),
            partition_key=partition_key,
            excluded=True,
        )
    if sig.execution_fidelity == ExecutionFidelity.EXECUTION_UNKNOWN:
        codes.append("execution_unknown_blocks_recurrence_evidence")
        return _Eligibility(
            episode_id=sig.episode_id,
            tier=EvidenceContributionTier.INELIGIBLE,
            direction=EvidenceUnitDirection.NEUTRAL,
            reason_codes=tuple(codes),
            partition_key=partition_key,
            excluded=True,
        )
    if sig.execution_fidelity == ExecutionFidelity.EXECUTED_WITH_MATERIAL_VARIATION:
        codes.append("material_variation_not_same_intervention")
        return _Eligibility(
            episode_id=sig.episode_id,
            tier=EvidenceContributionTier.INELIGIBLE,
            direction=EvidenceUnitDirection.NEUTRAL,
            reason_codes=tuple(codes),
            partition_key=partition_key,
            excluded=True,
        )
    if sig.execution_fidelity == ExecutionFidelity.PARTIALLY_EXECUTED:
        tier = EvidenceContributionTier.LIMITED
        codes.append("partial_execution_limited_evidence")

    if sig.attribution_assessment in {
        AttributionAssessment.CONFLICTING_EVIDENCE,
        AttributionAssessment.INSUFFICIENT_EVIDENCE,
        AttributionAssessment.NOT_ASSESSED,
    }:
        codes.append("attribution_insufficient_or_conflicting_excluded")
        return _Eligibility(
            episode_id=sig.episode_id,
            tier=EvidenceContributionTier.INELIGIBLE,
            direction=EvidenceUnitDirection.NEUTRAL,
            reason_codes=tuple(codes),
            partition_key=partition_key,
            excluded=True,
        )
    if sig.attribution_assessment == AttributionAssessment.TEMPORAL_ASSOCIATION:
        tier = EvidenceContributionTier.LIMITED
        codes.append("temporal_association_limited_evidence")

    if sig.observation_time_provenance in {
        ObservationTimeProvenance.CALLER_ASSERTED,
        ObservationTimeProvenance.UNKNOWN,
        ObservationTimeProvenance.DERIVED,
    }:
        tier = EvidenceContributionTier.LIMITED
        codes.append(f"{sig.observation_time_provenance.value}_chronology_limited_evidence")

    if sig.learning_signal_strength == LearningSignalStrength.WEAK:
        tier = EvidenceContributionTier.LIMITED
        codes.append("weak_learning_signal_limited_evidence")
    elif sig.learning_signal_strength == LearningSignalStrength.CANDIDATE:
        tier = EvidenceContributionTier.LIMITED
        codes.append("candidate_learning_signal_limited_evidence")

    return _Eligibility(
        episode_id=sig.episode_id,
        tier=tier,
        direction=direction,
        reason_codes=tuple(codes or ["strong_recurrence_evidence"]),
        partition_key=partition_key,
    )


def _build_hard_components(
    sigs: list[ExperienceContextSignature], comparisons: list[ExperienceComparison]
) -> tuple[tuple[str, ...], ...]:
    ids = sorted(sig.episode_id for sig in sigs)
    uf = _UnionFind(ids)
    for comparison in comparisons:
        if comparison.left_episode_id not in uf.parent or comparison.right_episode_id not in uf.parent:
            continue
        if comparison.independence == IndependenceStatus.DEPENDENT:
            uf.union(comparison.left_episode_id, comparison.right_episode_id)
    groups: dict[str, list[str]] = defaultdict(list)
    for episode_id in ids:
        groups[uf.find(episode_id)].append(episode_id)
    return tuple(tuple(sorted(group)) for group in sorted(groups.values(), key=lambda group: group[0]))


def _component_independence(component: tuple[str, ...], comparisons: list[ExperienceComparison]) -> IndependenceStatus:
    if len(component) > 1:
        return IndependenceStatus.DEPENDENT
    episode_id = component[0]
    statuses = [
        c.independence
        for c in comparisons
        if episode_id in {c.left_episode_id, c.right_episode_id}
        and c.independence in {IndependenceStatus.PARTIALLY_INDEPENDENT, IndependenceStatus.INDETERMINATE}
    ]
    if IndependenceStatus.PARTIALLY_INDEPENDENT in statuses:
        return IndependenceStatus.PARTIALLY_INDEPENDENT
    if IndependenceStatus.INDETERMINATE in statuses:
        return IndependenceStatus.INDETERMINATE
    return IndependenceStatus.INDEPENDENT


def _merge_tiers(tiers: set[EvidenceContributionTier]) -> EvidenceContributionTier:
    if EvidenceContributionTier.INELIGIBLE in tiers:
        return EvidenceContributionTier.INELIGIBLE
    if EvidenceContributionTier.LIMITED in tiers:
        return EvidenceContributionTier.LIMITED
    return EvidenceContributionTier.STRONG


def _merge_directions(directions: set[EvidenceUnitDirection]) -> EvidenceUnitDirection:
    directional = directions - {EvidenceUnitDirection.NEUTRAL}
    if not directional:
        return EvidenceUnitDirection.NEUTRAL
    if len(directional) > 1 or EvidenceUnitDirection.AMBIGUOUS in directional:
        return EvidenceUnitDirection.AMBIGUOUS
    return next(iter(directional))


def _build_evidence_units(
    *,
    components: list[tuple[str, ...]],
    eligibilities: dict[str, _Eligibility],
    comparisons: list[ExperienceComparison],
) -> tuple[_EvidenceUnit, ...]:
    units: list[_EvidenceUnit] = []
    for component in components:
        component_eligibilities = [eligibilities[episode_id] for episode_id in component]
        usable = [item for item in component_eligibilities if item.tier != EvidenceContributionTier.INELIGIBLE]
        if not usable:
            continue
        direction = _merge_directions({item.direction for item in usable})
        tier = _merge_tiers({item.tier for item in usable})
        independence = _component_independence(component, comparisons)
        codes = tuple(sorted({code for item in component_eligibilities for code in item.reason_codes}))
        units.append(
            _EvidenceUnit(
                episode_ids=component,
                direction=direction,
                tier=tier,
                independence=independence,
                reason_codes=codes,
            )
        )
    return tuple(units)


def _assessment_from_units(
    units: tuple[_EvidenceUnit, ...],
) -> RecurrenceAssessment | None:
    directional_units = [
        u for u in units if u.direction in {EvidenceUnitDirection.SUPPORT, EvidenceUnitDirection.CONTRADICTION}
    ]
    if len(directional_units) < 2:
        return None

    strong_independent_support = [
        u
        for u in units
        if u.direction == EvidenceUnitDirection.SUPPORT
        and u.tier == EvidenceContributionTier.STRONG
        and u.independence == IndependenceStatus.INDEPENDENT
    ]
    support_units = [u for u in units if u.direction == EvidenceUnitDirection.SUPPORT]
    limited_support_units = [u for u in support_units if u.tier == EvidenceContributionTier.LIMITED]
    dependent_support_units = [
        u
        for u in support_units
        if u.independence
        in {
            IndependenceStatus.DEPENDENT,
            IndependenceStatus.PARTIALLY_INDEPENDENT,
            IndependenceStatus.INDETERMINATE,
        }
    ]
    contradiction_units = [u for u in units if u.direction == EvidenceUnitDirection.CONTRADICTION]
    strong_independent_contradictions = [
        u
        for u in contradiction_units
        if u.tier == EvidenceContributionTier.STRONG and u.independence == IndependenceStatus.INDEPENDENT
    ]
    limited_contradiction_units = [u for u in contradiction_units if u.tier == EvidenceContributionTier.LIMITED]
    dependent_contradiction_units = [
        u
        for u in contradiction_units
        if u.independence
        in {
            IndependenceStatus.DEPENDENT,
            IndependenceStatus.PARTIALLY_INDEPENDENT,
            IndependenceStatus.INDETERMINATE,
        }
    ]
    ambiguous_units = [u for u in units if u.direction == EvidenceUnitDirection.AMBIGUOUS]
    codes = sorted({code for unit in units for code in unit.reason_codes})
    if limited_support_units:
        codes.append("limited_support_does_not_create_supported_recurrence")
    if limited_contradiction_units:
        codes.append("limited_contradiction_does_not_create_strong_invalidation")
    if dependent_contradiction_units:
        codes.append("dependent_contradiction_does_not_create_strong_invalidation")
    if ambiguous_units:
        codes.append("dependent_component_contains_conflicting_directions")

    if len(strong_independent_contradictions) >= 2 and len(strong_independent_contradictions) >= len(
        strong_independent_support
    ):
        strength = RecurrenceStrength.INVALIDATED
        codes.append("repeated_strong_independent_contradictions")
    elif strong_independent_contradictions and (support_units or ambiguous_units):
        strength = RecurrenceStrength.CONTESTED
        codes.append("strong_independent_comparable_counterexample_present")
    elif len(strong_independent_support) >= 3:
        strength = RecurrenceStrength.SUPPORTED
    elif len(support_units) >= 2:
        strength = RecurrenceStrength.EMERGING if strong_independent_support else RecurrenceStrength.WEAK
    elif contradiction_units:
        strength = RecurrenceStrength.WEAK
    else:
        return None

    if any(u.independence == IndependenceStatus.DEPENDENT for u in units):
        independence = IndependenceStatus.DEPENDENT
    elif any(u.independence == IndependenceStatus.PARTIALLY_INDEPENDENT for u in units):
        independence = IndependenceStatus.PARTIALLY_INDEPENDENT
    elif any(u.independence == IndependenceStatus.INDETERMINATE for u in units):
        independence = IndependenceStatus.INDETERMINATE
    else:
        independence = IndependenceStatus.INDEPENDENT

    has_limited_evidence = bool(limited_support_units or limited_contradiction_units)
    evidence_limitation = "limited_evidence_present" if has_limited_evidence else None
    return RecurrenceAssessment(
        strength=strength,
        comparability=ComparabilityStatus.COMPARABLE,
        independence=independence,
        independent_support_count=len(strong_independent_support),
        dependent_support_count=len(dependent_support_units),
        strong_independent_contradiction_count=len(strong_independent_contradictions),
        limited_support_count=len(limited_support_units),
        limited_contradiction_count=len(limited_contradiction_units),
        dependent_contradiction_count=len(dependent_contradiction_units),
        ambiguous_unit_count=len(ambiguous_units),
        evidence_limitation=evidence_limitation,
        reason_codes=tuple(dict.fromkeys(codes)),
    )


def _validate_unique_episode_ids(episodes: list[ExperienceEpisodeInput]) -> None:
    ids = [episode.episode_id for episode in episodes]
    duplicates = sorted({episode_id for episode_id in ids if ids.count(episode_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate episode_id values are not allowed: {', '.join(duplicates)}")


def _active_scope_conditions(sigs: list[ExperienceContextSignature]) -> tuple[str, ...]:
    return tuple(sorted({condition for sig in sigs for condition in sig.scope_conditions}))


def evaluate_experience_set(
    episodes: list[ExperienceEpisodeInput],
) -> ExperienceIntelligenceResult:
    _validate_unique_episode_ids(episodes)
    signatures = sorted((derive_context_signature(e) for e in episodes), key=lambda sig: sig.episode_id)
    by_id = {e.episode_id: e for e in episodes}
    comparisons = tuple(
        _compare(signatures[i], signatures[j]) for i in range(len(signatures)) for j in range(i + 1, len(signatures))
    )
    partition_payloads: dict[str, dict[str, object]] = {}
    partitions: dict[str, list[ExperienceContextSignature]] = defaultdict(list)
    unclassified: list[str] = []
    excluded: list[str] = []
    episode_explanations: dict[str, tuple[str, ...]] = {}
    eligibility_by_id: dict[str, _Eligibility] = {}

    for sig in signatures:
        payload = _partition_payload(sig)
        key = _stable_key(payload) if payload is not None else None
        if key is not None and payload is not None:
            partition_payloads[key] = payload
            partitions[key].append(sig)

    for key, sigs in partitions.items():
        active_scope = _active_scope_conditions(sigs)
        for sig in sigs:
            eligibility = _eligibility(
                sig=sig,
                signal=by_id[sig.episode_id].signal,
                partition_key=key,
                active_scope_conditions=active_scope,
            )
            eligibility_by_id[sig.episode_id] = eligibility
            if eligibility.excluded:
                excluded.append(sig.episode_id)
            episode_explanations[sig.episode_id] = eligibility.reason_codes

    for sig in signatures:
        if sig.episode_id in eligibility_by_id:
            continue
        eligibility = _eligibility(
            sig=sig,
            signal=by_id[sig.episode_id].signal,
            partition_key=None,
            active_scope_conditions=(),
        )
        eligibility_by_id[sig.episode_id] = eligibility
        unclassified.append(sig.episode_id)
        episode_explanations[sig.episode_id] = eligibility.reason_codes

    candidates: list[ExperiencePatternCandidate] = []
    all_dependent_groups: set[tuple[str, ...]] = set()
    partition_explanations: dict[str, tuple[str, ...]] = {}

    for key in sorted(partitions):
        sigs = sorted(partitions[key], key=lambda sig: sig.episode_id)
        partition_comparisons = [
            c
            for c in comparisons
            if c.left_episode_id in {s.episode_id for s in sigs} and c.right_episode_id in {s.episode_id for s in sigs}
        ]
        components = _build_hard_components(sigs, partition_comparisons)
        dependence_groups = tuple(group for group in components if len(group) > 1)
        for group in dependence_groups:
            all_dependent_groups.add(group)
        units = _build_evidence_units(
            components=list(components),
            eligibilities=eligibility_by_id,
            comparisons=partition_comparisons,
        )
        assessment = _assessment_from_units(units)
        partition_episode_ids = tuple(sig.episode_id for sig in sigs)
        partition_excluded = tuple(sorted(eid for eid in partition_episode_ids if eligibility_by_id[eid].excluded))
        non_candidate_codes: list[str] = []
        if assessment is None:
            non_candidate_codes.append("partition_did_not_earn_recurrence_candidate")
            if len([u for u in units if u.direction != EvidenceUnitDirection.NEUTRAL]) < 2:
                non_candidate_codes.append("fewer_than_two_directional_recurrence_units")
            if len(sigs) == 1:
                non_candidate_codes.append("singleton_partition_not_candidate")
            partition_explanations[key] = tuple(non_candidate_codes)
            continue

        support_ids = tuple(
            sorted(eid for unit in units if unit.direction == EvidenceUnitDirection.SUPPORT for eid in unit.episode_ids)
        )
        contradiction_ids = tuple(
            sorted(
                eid
                for unit in units
                if unit.direction == EvidenceUnitDirection.CONTRADICTION
                for eid in unit.episode_ids
            )
        )
        neutral_ids = tuple(
            sorted(eid for unit in units if unit.direction == EvidenceUnitDirection.NEUTRAL for eid in unit.episode_ids)
        )
        ambiguous_ids = tuple(
            sorted(
                eid for unit in units if unit.direction == EvidenceUnitDirection.AMBIGUOUS for eid in unit.episode_ids
            )
        )
        evaluated_times = [by_id[eid].signal.evaluated_at for eid in partition_episode_ids]
        common_scope = (
            sigs[0].scope_conditions if all(sig.scope_conditions == sigs[0].scope_conditions for sig in sigs) else ()
        )
        conflicting_scope = tuple(
            sorted({condition for sig in sigs for condition in sig.scope_conditions} - set(common_scope))
        )
        invalidations = tuple(sorted({condition for sig in sigs for condition in sig.invalidation_conditions}))
        common_objective_dimensions = (
            sigs[0].objective_dimensions
            if all(sig.objective_dimensions == sigs[0].objective_dimensions for sig in sigs)
            else ()
        )
        candidate_explanation_codes = list(assessment.reason_codes)
        if not common_objective_dimensions and any(sig.objective_dimensions for sig in sigs):
            candidate_explanation_codes.append("caller_objective_context_diverged")
        payload = partition_payloads[key]
        candidate_payload = {
            "partition_key": key,
            "recurrence_algorithm": EXPERIENCE_INTELLIGENCE_ALGORITHM,
        }
        candidate_id = (
            f"experience-pattern-v1:{hashlib.sha256(_stable_json(candidate_payload).encode('utf-8')).hexdigest()[:16]}"
        )
        candidates.append(
            ExperiencePatternCandidate(
                candidate_id=candidate_id,
                partition_key=key,
                recommendation_class=str(payload["recommendation_class"]),
                subject_types=tuple(cast(list[str], payload["subject_types"])),
                goal_id=str(payload["goal_id"]),
                objective_dimensions=common_objective_dimensions,
                supporting_episode_ids=support_ids,
                contradicting_episode_ids=contradiction_ids,
                neutral_episode_ids=neutral_ids,
                ambiguous_episode_ids=ambiguous_ids,
                excluded_episode_ids=partition_excluded,
                dependent_episode_groups=dependence_groups,
                common_scope_conditions=common_scope,
                conflicting_scope_conditions=conflicting_scope,
                invalidation_conditions=invalidations,
                earliest_evaluated_at=min(evaluated_times) if evaluated_times else None,
                latest_evaluated_at=max(evaluated_times) if evaluated_times else None,
                recurrence=assessment,
                explanation_codes=tuple(candidate_explanation_codes),
            )
        )
        partition_explanations[key] = tuple(candidate_explanation_codes)

    return ExperienceIntelligenceResult(
        signatures=tuple(signatures),
        comparisons=comparisons,
        pattern_candidates=tuple(sorted(candidates, key=lambda candidate: candidate.partition_key)),
        excluded_episode_ids=tuple(sorted(excluded)),
        unclassified_episode_ids=tuple(sorted(unclassified)),
        dependent_episode_groups=tuple(sorted(all_dependent_groups)),
        partition_explanations={key: partition_explanations[key] for key in sorted(partition_explanations)},
        episode_explanations={key: episode_explanations[key] for key in sorted(episode_explanations)},
    )
