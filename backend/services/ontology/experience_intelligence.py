"""Experience Intelligence Slice 1 — equivalence and recurrence eligibility.

Compares DecisionLearningSignal observations without promoting them to knowledge,
policy, memory, behavior changes, or action execution.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.services.ontology.decision_feedback import (
    DecisionEffectivenessStatus,
    DecisionLearningSignal,
)
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


class ExperienceEpisodeInput(BaseModel):
    """One episode plus structured recurrence semantics not present in older signals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_id: str = Field(min_length=1, max_length=160)
    signal: DecisionLearningSignal
    recommendation_class: str | None = Field(default=None, max_length=160)
    objective_dimensions: tuple[str, ...] = ()
    attribution_evidence_ids: tuple[str, ...] = ()
    observation_time_provenance: str | None = None
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
    decision_algorithm: str
    decision_algorithm_version: str | None = None
    effective_dimensions: tuple[str, ...] = ()
    ineffective_dimensions: tuple[str, ...] = ()
    attribution_assessment: str
    observation_time_provenance: str | None = None
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
    independent_contradiction_count: int
    attribution_cap: str | None = None
    reason_codes: tuple[str, ...] = ()


class ExperiencePatternCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    candidate_id: str
    partition_key: str
    recommendation_class: str
    subject_types: tuple[str, ...]
    goal_id: str | None = None
    objective_dimensions: tuple[str, ...] = ()
    supporting_episode_ids: tuple[str, ...] = ()
    contradicting_episode_ids: tuple[str, ...] = ()
    neutral_episode_ids: tuple[str, ...] = ()
    excluded_episode_ids: tuple[str, ...] = ()
    dependent_episode_groups: tuple[tuple[str, ...], ...] = ()
    common_scope_conditions: tuple[str, ...] = ()
    conflicting_scope_conditions: tuple[str, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()
    earliest_observed_at: datetime | None = None
    latest_observed_at: datetime | None = None
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
    epistemic_limits: tuple[str, ...] = (
        "candidate_only_not_knowledge",
        "candidate_only_not_policy",
        "non_causal_recurrence_assessment",
        "no_memory_or_behavior_change",
    )
    algorithm: str = EXPERIENCE_INTELLIGENCE_ALGORITHM


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().casefold()
    return stripped or None


def _dedupe(items: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(i.strip().casefold() for i in items if i and i.strip()))


def derive_context_signature(episode: ExperienceEpisodeInput) -> ExperienceContextSignature:
    signal = episode.signal
    return ExperienceContextSignature(
        episode_id=episode.episode_id,
        exact_signal_id=signal.signal_id,
        exact_decision_id=signal.decision_id,
        exact_subject_refs=tuple(f"{r.object_type.value}:{r.object_id}" for r in signal.subject_refs),
        exact_goal_id=signal.goal_id,
        semantic_subject_types=_dedupe(tuple(r.object_type.value for r in signal.subject_refs)),
        recommendation_class=_norm(episode.recommendation_class),
        objective_dimensions=_dedupe(episode.objective_dimensions),
        decision_algorithm=signal.algorithm,
        decision_algorithm_version=None,
        effective_dimensions=_dedupe(tuple(signal.effective_dimensions)),
        ineffective_dimensions=_dedupe(tuple(signal.ineffective_dimensions)),
        attribution_assessment=signal.attribution_strength.value,
        observation_time_provenance=episode.observation_time_provenance,
        scope_conditions=_dedupe(tuple(signal.scope_conditions)),
        invalidation_conditions=_dedupe(tuple(signal.invalidation_conditions)),
        supporting_evidence_ids=_dedupe(tuple(signal.supporting_evidence_ids) + episode.attribution_evidence_ids),
        lineage_ids=_dedupe(episode.lineage_ids),
    )


def _goal_key(sig: ExperienceContextSignature) -> tuple[str, str | tuple[str, ...]] | None:
    if sig.exact_goal_id:
        return ("goal", sig.exact_goal_id)
    if sig.objective_dimensions:
        return ("objectives", sig.objective_dimensions)
    return None


def _partition_key(sig: ExperienceContextSignature) -> str | None:
    if not sig.recommendation_class:
        return None
    goal = _goal_key(sig)
    if not sig.semantic_subject_types or goal is None:
        return None
    return repr((sig.semantic_subject_types, sig.recommendation_class, goal))


def _compare(a: ExperienceContextSignature, b: ExperienceContextSignature) -> ExperienceComparison:
    codes: list[str] = []
    if not a.recommendation_class or not b.recommendation_class:
        codes.append("missing_recommendation_class_excluded")
        comp = ComparabilityStatus.INSUFFICIENT_CONTEXT
    elif a.recommendation_class != b.recommendation_class:
        codes.append("different_recommendation_class_partition")
        comp = ComparabilityStatus.INCOMPATIBLE
    elif a.semantic_subject_types != b.semantic_subject_types:
        codes.append("different_subject_type")
        comp = ComparabilityStatus.INCOMPATIBLE
    elif a.exact_goal_id and b.exact_goal_id and a.exact_goal_id != b.exact_goal_id:
        codes.append("different_goal_id_without_semantic_equivalence")
        comp = ComparabilityStatus.INCOMPATIBLE
    elif (
        a.exact_goal_id != b.exact_goal_id
        and a.objective_dimensions
        and a.objective_dimensions == b.objective_dimensions
    ):
        codes.append("typed_objective_equivalence_partial")
        comp = ComparabilityStatus.PARTIALLY_COMPARABLE
    elif _goal_key(a) is None or _goal_key(b) is None:
        codes.append("goal_semantics_insufficient")
        comp = ComparabilityStatus.INSUFFICIENT_CONTEXT
    else:
        codes.append("same_semantic_partition")
        comp = ComparabilityStatus.COMPARABLE
    indep, indep_codes = _pair_independence(a, b)
    return ExperienceComparison(
        left_episode_id=a.episode_id,
        right_episode_id=b.episode_id,
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
    if set(a.supporting_evidence_ids) & set(b.supporting_evidence_ids):
        partial = True
        codes.append("overlapping_evidence_ids")
    if set(a.exact_subject_refs) & set(b.exact_subject_refs):
        partial = True
        codes.append("same_subject_instance_correlation")
    if set(a.lineage_ids) & set(b.lineage_ids):
        partial = True
        codes.append("reused_lineage")
    if hard:
        return IndependenceStatus.DEPENDENT, codes
    if partial:
        return IndependenceStatus.PARTIALLY_INDEPENDENT, codes
    if not a.supporting_evidence_ids or not b.supporting_evidence_ids:
        return IndependenceStatus.INDETERMINATE, [*codes, "independence_evidence_insufficient"]
    return IndependenceStatus.INDEPENDENT, [*codes, "no_dependence_signal_detected"]


def _is_support(signal: DecisionLearningSignal) -> bool:
    return signal.effectiveness.status in {
        DecisionEffectivenessStatus.HIGHLY_EFFECTIVE,
        DecisionEffectivenessStatus.EFFECTIVE,
        DecisionEffectivenessStatus.PARTIALLY_EFFECTIVE,
    }


def _is_contradiction(signal: DecisionLearningSignal) -> bool:
    return signal.effectiveness.status in {
        DecisionEffectivenessStatus.INEFFECTIVE,
        DecisionEffectivenessStatus.COUNTERPRODUCTIVE,
        DecisionEffectivenessStatus.NOT_EXECUTED,
    }


def _attribution_cap(signals: list[DecisionLearningSignal]) -> str | None:
    attrs = {s.attribution_strength for s in signals}
    if attrs & {
        AttributionAssessment.CONFLICTING_EVIDENCE,
        AttributionAssessment.INSUFFICIENT_EVIDENCE,
        AttributionAssessment.NOT_ASSESSED,
    }:
        return "weak_attribution_caps_strength"
    if attrs == {AttributionAssessment.TEMPORAL_ASSOCIATION}:
        return "temporal_association_caps_below_supported"
    return None


def _independent_count(ids: list[str], comparisons: list[ExperienceComparison]) -> tuple[int, int, IndependenceStatus]:
    if len(ids) <= 1:
        return len(ids), 0, IndependenceStatus.INDETERMINATE if len(ids) == 1 else IndependenceStatus.INDEPENDENT
    dependent = set()
    partial = set()
    for c in comparisons:
        if c.left_episode_id in ids and c.right_episode_id in ids:
            if c.independence == IndependenceStatus.DEPENDENT:
                dependent.add(c.right_episode_id)
            elif c.independence in {IndependenceStatus.PARTIALLY_INDEPENDENT, IndependenceStatus.INDETERMINATE}:
                partial.add(c.right_episode_id)
    independent = max(1, len(ids) - len(dependent) - len(partial)) if ids else 0
    if dependent:
        status = IndependenceStatus.DEPENDENT
    elif partial:
        status = IndependenceStatus.PARTIALLY_INDEPENDENT
    else:
        status = IndependenceStatus.INDEPENDENT
    return independent, len(dependent) + len(partial), status


def evaluate_experience_set(episodes: list[ExperienceEpisodeInput]) -> ExperienceIntelligenceResult:
    signatures = [derive_context_signature(e) for e in episodes]
    by_id = {e.episode_id: e for e in episodes}
    comparisons = [
        _compare(signatures[i], signatures[j]) for i in range(len(signatures)) for j in range(i + 1, len(signatures))
    ]
    partitions: dict[str, list[ExperienceContextSignature]] = defaultdict(list)
    excluded: list[str] = []
    unclassified: list[str] = []
    explanations: dict[str, tuple[str, ...]] = {}
    for sig in signatures:
        key = _partition_key(sig)
        if key is None:
            unclassified.append(sig.episode_id)
            explanations[sig.episode_id] = ("missing_recommendation_class_or_semantic_context",)
        else:
            partitions[key].append(sig)
    candidates: list[ExperiencePatternCandidate] = []
    all_dependent_groups: list[tuple[str, ...]] = []
    for key, sigs in partitions.items():
        ids = [s.episode_id for s in sigs]
        signals = [by_id[i].signal for i in ids]
        support = [i for i, s in zip(ids, signals, strict=True) if _is_support(s)]
        contra = [i for i, s in zip(ids, signals, strict=True) if _is_contradiction(s)]
        neutral = [i for i in ids if i not in support and i not in contra]
        indep_support, dep_support, indep_status = _independent_count(support, comparisons)
        indep_contra, _, _ = _independent_count(contra, comparisons)
        cap = _attribution_cap([by_id[i].signal for i in support]) if support else None
        codes: list[str] = []
        if len(sigs) == 1:
            codes.append("single_episode_cannot_establish_recurrence")
        if cap:
            codes.append(cap)
        if indep_contra >= 2 and indep_contra >= indep_support:
            strength = RecurrenceStrength.INVALIDATED
            codes.append("repeated_comparable_contradictions")
        elif indep_contra and indep_support:
            strength = RecurrenceStrength.CONTESTED
            codes.append("comparable_counterexample_present")
        elif indep_support >= 3 and indep_status == IndependenceStatus.INDEPENDENT and cap is None:
            strength = RecurrenceStrength.SUPPORTED
        elif indep_support >= 2 and indep_status in {
            IndependenceStatus.INDEPENDENT,
            IndependenceStatus.PARTIALLY_INDEPENDENT,
        }:
            strength = RecurrenceStrength.EMERGING
        else:
            strength = RecurrenceStrength.WEAK
        groups = []
        for c in comparisons:
            if (
                c.left_episode_id in ids
                and c.right_episode_id in ids
                and c.independence != IndependenceStatus.INDEPENDENT
            ):
                groups.append((c.left_episode_id, c.right_episode_id))
        all_dependent_groups.extend(groups)
        times = [by_id[i].signal.evaluated_at for i in ids if by_id[i].signal.evaluated_at]
        scopes = [set(s.scope_conditions) for s in sigs]
        common_scope = tuple(sorted(set.intersection(*scopes))) if scopes and all(scopes) else ()
        conflicting_scope = tuple(sorted(set.union(*scopes) - set(common_scope))) if scopes else ()
        first = sigs[0]
        candidates.append(
            ExperiencePatternCandidate(
                candidate_id=f"experience-pattern-{len(candidates) + 1}",
                partition_key=key,
                recommendation_class=first.recommendation_class or "",
                subject_types=first.semantic_subject_types,
                goal_id=first.exact_goal_id,
                objective_dimensions=first.objective_dimensions,
                supporting_episode_ids=tuple(support),
                contradicting_episode_ids=tuple(contra),
                neutral_episode_ids=tuple(neutral),
                excluded_episode_ids=tuple(excluded),
                dependent_episode_groups=tuple(groups),
                common_scope_conditions=common_scope,
                conflicting_scope_conditions=conflicting_scope,
                invalidation_conditions=tuple(sorted({x for s in sigs for x in s.invalidation_conditions})),
                earliest_observed_at=min(times) if times else None,
                latest_observed_at=max(times) if times else None,
                recurrence=RecurrenceAssessment(
                    strength=strength,
                    comparability=ComparabilityStatus.COMPARABLE,
                    independence=indep_status,
                    independent_support_count=indep_support,
                    dependent_support_count=dep_support,
                    independent_contradiction_count=indep_contra,
                    attribution_cap=cap,
                    reason_codes=tuple(codes),
                ),
                explanation_codes=tuple(codes),
            )
        )
    return ExperienceIntelligenceResult(
        signatures=tuple(signatures),
        comparisons=tuple(comparisons),
        pattern_candidates=tuple(candidates),
        excluded_episode_ids=tuple(excluded),
        unclassified_episode_ids=tuple(unclassified),
        dependent_episode_groups=tuple(all_dependent_groups),
        partition_explanations=explanations,
    )
