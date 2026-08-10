"""Experience Intelligence Slice 1 — multi-episode comparison and recurrence.

Architectural position:
  Evidence → Business Object → State/Event → Goal/KPI → Evaluation → Decision
  → Outcome → Decision Feedback → Experience

#414 owns Experience. Compares multiple DecisionLearningSignals and produces a
bounded recurrence / pattern *candidate*. Does NOT convert repeated signals into
knowledge, policy, memory, or behavior change.

Invariant: Observation ≠ pattern ≠ knowledge ≠ policy.

A DecisionLearningSignal is one episode. Experience Intelligence asks whether
comparable, independent episodes recur under shared scope conditions and what
counterexamples exist. The strongest output remains a candidate, never proven
knowledge.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.services.ontology.decision_feedback import (
    DecisionLearningSignal,
    LearningSignalStrength,
)
from backend.services.ontology.observation_attribution import (
    AttributionAssessment,
    ObservationTimeProvenance,
)
from backend.services.ontology.types import BusinessObjectRef

EXPERIENCE_INTELLIGENCE_SCHEMA_VERSION = 1


class ComparabilityStatus(StrEnum):
    COMPARABLE = "comparable"
    PARTIALLY_COMPARABLE = "partially_comparable"
    NOT_COMPARABLE = "not_comparable"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class IndependenceStatus(StrEnum):
    INDEPENDENT = "independent"
    PARTIALLY_INDEPENDENT = "partially_independent"
    DEPENDENT = "dependent"
    UNKNOWN = "unknown"


class RecurrenceStrength(StrEnum):
    """Episode-set recurrence strength. Never 'proven'."""

    WEAK = "weak"
    EMERGING = "emerging"
    SUPPORTED = "supported"
    CONTESTED = "contested"
    INVALIDATED = "invalidated"


class ExperienceEpisodeInput(BaseModel):
    """One episode supplied for multi-episode comparison.

    DecisionLearningSignal is the primary source. Optional provenance fields
    recover attribution quality without rewriting #412/#413 contracts.
    """

    model_config = ConfigDict(extra="forbid")

    signal: DecisionLearningSignal
    observation_provenance: ObservationTimeProvenance | None = None
    attribution_earned: bool | None = Field(
        default=None,
        description="True when AttributionAssessmentEvidence earned the attribution level",
    )
    decision_algorithm: str | None = Field(
        default=None,
        max_length=160,
        description="algorithm_name@version from DecisionSnapshot when available",
    )
    recommendation_class: str | None = Field(
        default=None,
        max_length=240,
        description="Stable recommendation class key; free-form text alone is insufficient",
    )


class ExperienceComparabilityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ComparabilityStatus
    confidence: float = Field(ge=0, le=1)
    shared_goal_id: str | None = None
    shared_subject_keys: list[str] = Field(default_factory=list)
    shared_algorithm: str | None = None
    shared_fidelity_class: str | None = None
    dimension_overlap: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    explanation_codes: list[str] = Field(default_factory=list)
    algorithm: str = "experience_comparability_v1"


class ExperienceIndependenceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: IndependenceStatus
    confidence: float = Field(ge=0, le=1)
    unique_decision_ids: int = 0
    unique_signal_ids: int = 0
    duplicate_decision_ids: list[str] = Field(default_factory=list)
    overlapping_evidence_ids: list[str] = Field(default_factory=list)
    explanation_codes: list[str] = Field(default_factory=list)
    algorithm: str = "experience_independence_v1"


class ExperienceComparison(BaseModel):
    """Pairwise / set-level comparability + independence result."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    comparison_id: str
    episode_count: int
    signal_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    comparability: ExperienceComparabilityAssessment
    independence: ExperienceIndependenceAssessment
    evaluated_at: datetime
    explanation_codes: list[str] = Field(default_factory=list)
    algorithm: str = "experience_comparison_v1"


class RecurrenceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RecurrenceStrength
    confidence: float = Field(ge=0, le=1)
    supporting_signal_ids: list[str] = Field(default_factory=list)
    contradicting_signal_ids: list[str] = Field(default_factory=list)
    supporting_count: int = 0
    contradicting_count: int = 0
    independent_supporting_count: int = 0
    weak_attribution_count: int = 0
    caller_asserted_provenance_count: int = 0
    explanation_codes: list[str] = Field(default_factory=list)
    algorithm: str = "experience_recurrence_v1"


class ExperiencePatternCandidate(BaseModel):
    """Candidate pattern from multiple episodes. NOT knowledge or policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    pattern_id: str
    comparison_id: str
    signal_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    subject_refs: list[BusinessObjectRef] = Field(default_factory=list)
    goal_id: str | None = None
    comparability: ExperienceComparabilityAssessment
    independence: ExperienceIndependenceAssessment
    recurrence: RecurrenceAssessment
    candidate_pattern: str = Field(default="", max_length=2000)
    scope_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    effective_dimensions: list[str] = Field(default_factory=list)
    ineffective_dimensions: list[str] = Field(default_factory=list)
    attribution_floor: AttributionAssessment = AttributionAssessment.NOT_ASSESSED
    algorithm: str = "experience_pattern_candidate_v1"
    evaluated_at: datetime
    is_knowledge: Literal[False] = False
    is_policy: Literal[False] = False
    notes: str = (
        "An ExperiencePatternCandidate is a multi-episode observation. "
        "It is not knowledge, policy, or a globally valid rule."
    )


class ExperienceIntelligenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    result_id: str
    comparison: ExperienceComparison
    pattern_candidate: ExperiencePatternCandidate | None = None
    evaluated_at: datetime
    algorithm: str = "experience_intelligence_episode_set_v1"
    explanation_codes: list[str] = Field(default_factory=list)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _subject_key(ref: BusinessObjectRef) -> str:
    return f"{ref.object_type}:{ref.object_id}"


def _subject_keys(refs: list[BusinessObjectRef]) -> set[str]:
    return {_subject_key(r) for r in refs}


def assess_experience_comparability(
    episodes: list[ExperienceEpisodeInput],
) -> ExperienceComparabilityAssessment:
    """experience_comparability_v1 — fail closed on foreign context."""

    codes: list[str] = []
    if len(episodes) < 2:
        return ExperienceComparabilityAssessment(
            status=ComparabilityStatus.INSUFFICIENT_CONTEXT,
            confidence=0.3,
            blocking_reasons=["fewer_than_two_episodes"],
            explanation_codes=["insufficient_episodes_for_comparison"],
        )

    signals = [e.signal for e in episodes]
    goal_ids = {s.goal_id for s in signals if s.goal_id}
    subject_sets = [_subject_keys(s.subject_refs) for s in signals]
    algorithms = {e.decision_algorithm for e in episodes if e.decision_algorithm}
    fidelities = {s.execution_fidelity.value for s in signals}
    rec_classes = {e.recommendation_class for e in episodes if e.recommendation_class}

    blocking: list[str] = []
    shared_goal: str | None = None
    if len(goal_ids) > 1:
        blocking.append("goal_id_mismatch")
        codes.append("foreign_goal_rejected")
    elif len(goal_ids) == 1:
        shared_goal = next(iter(goal_ids))
    elif not any(s.goal_id for s in signals):
        codes.append("goal_unscoped")

    shared_subjects: list[str] = []
    if subject_sets and all(subject_sets):
        intersection = set.intersection(*subject_sets)
        if not intersection:
            non_empty = [s for s in subject_sets if s]
            if len(non_empty) >= 2 and not set.intersection(*non_empty):
                blocking.append("subject_incompatible")
                codes.append("foreign_subject_rejected")
        else:
            shared_subjects = sorted(intersection)
    elif any(subject_sets) and not all(subject_sets):
        codes.append("partial_subject_coverage")

    shared_algorithm: str | None = None
    if len(algorithms) > 1:
        blocking.append("algorithm_mismatch")
        codes.append("algorithm_lineage_diverged")
    elif len(algorithms) == 1:
        shared_algorithm = next(iter(algorithms))

    shared_fidelity: str | None = None
    if len(fidelities) == 1:
        shared_fidelity = next(iter(fidelities))
    else:
        codes.append("execution_fidelity_diverged")

    if len(rec_classes) > 1:
        codes.append("recommendation_class_diverged")

    all_eff = [set(s.effective_dimensions) for s in signals]
    dim_overlap: list[str] = []
    if all_eff and any(all_eff):
        non_empty_eff = [d for d in all_eff if d]
        if non_empty_eff:
            dim_overlap = (
                sorted(set.intersection(*non_empty_eff)) if len(non_empty_eff) > 1 else sorted(non_empty_eff[0])
            )

    if blocking:
        status = ComparabilityStatus.NOT_COMPARABLE
        conf = 0.85
        codes.append("comparability_blocked")
    elif len(goal_ids) <= 1 and (shared_subjects or not any(subject_sets)):
        if len(fidelities) == 1 and (len(algorithms) <= 1):
            status = ComparabilityStatus.COMPARABLE
            conf = 0.8
            codes.append("episodes_comparable")
        else:
            status = ComparabilityStatus.PARTIALLY_COMPARABLE
            conf = 0.55
            codes.append("partial_comparability")
    else:
        status = ComparabilityStatus.PARTIALLY_COMPARABLE
        conf = 0.5
        codes.append("partial_comparability")

    return ExperienceComparabilityAssessment(
        status=status,
        confidence=round(conf, 4),
        shared_goal_id=shared_goal,
        shared_subject_keys=shared_subjects,
        shared_algorithm=shared_algorithm,
        shared_fidelity_class=shared_fidelity,
        dimension_overlap=dim_overlap,
        blocking_reasons=blocking,
        explanation_codes=_dedupe(codes),
    )


def assess_experience_independence(
    episodes: list[ExperienceEpisodeInput],
) -> ExperienceIndependenceAssessment:
    """experience_independence_v1 — duplicate decision/signal/evidence fails closed."""

    codes: list[str] = []
    if not episodes:
        return ExperienceIndependenceAssessment(
            status=IndependenceStatus.UNKNOWN,
            confidence=0.2,
            explanation_codes=["no_episodes"],
        )

    decision_ids = [e.signal.decision_id for e in episodes]
    signal_ids = [e.signal.signal_id for e in episodes]
    unique_decisions = set(decision_ids)
    unique_signals = set(signal_ids)

    from collections import Counter

    decision_counts = Counter(decision_ids)
    dup_decisions = sorted(d for d, c in decision_counts.items() if c > 1)

    evidence_sets = [set(e.signal.supporting_evidence_ids) for e in episodes]
    overlapping: list[str] = []
    for i in range(len(evidence_sets)):
        for j in range(i + 1, len(evidence_sets)):
            shared = evidence_sets[i] & evidence_sets[j]
            overlapping.extend(sorted(shared))
    overlapping = _dedupe(overlapping)

    if len(unique_signals) < len(signal_ids):
        codes.append("duplicate_signal_ids")
    if dup_decisions:
        codes.append("duplicate_decision_ids")
    if overlapping:
        codes.append("overlapping_evidence_lineage")

    if dup_decisions or len(unique_signals) < len(signal_ids):
        status = IndependenceStatus.DEPENDENT
        conf = 0.85
        codes.append("episodes_not_independent")
    elif overlapping and len(overlapping) >= 2:
        status = IndependenceStatus.PARTIALLY_INDEPENDENT
        conf = 0.55
        codes.append("partial_evidence_independence")
    elif overlapping:
        status = IndependenceStatus.PARTIALLY_INDEPENDENT
        conf = 0.6
        codes.append("minor_evidence_overlap")
    else:
        status = IndependenceStatus.INDEPENDENT
        conf = 0.8
        codes.append("episodes_independent")

    return ExperienceIndependenceAssessment(
        status=status,
        confidence=round(conf, 4),
        unique_decision_ids=len(unique_decisions),
        unique_signal_ids=len(unique_signals),
        duplicate_decision_ids=dup_decisions,
        overlapping_evidence_ids=overlapping,
        explanation_codes=_dedupe(codes),
    )


def assess_experience_recurrence(
    *,
    episodes: list[ExperienceEpisodeInput],
    comparability: ExperienceComparabilityAssessment,
    independence: ExperienceIndependenceAssessment,
) -> RecurrenceAssessment:
    """experience_recurrence_v1 — counterexamples mandatory; attribution quality survives."""

    codes: list[str] = []
    if comparability.status == ComparabilityStatus.NOT_COMPARABLE:
        return RecurrenceAssessment(
            status=RecurrenceStrength.WEAK,
            confidence=0.4,
            explanation_codes=["not_comparable_blocks_recurrence"],
        )
    if comparability.status == ComparabilityStatus.INSUFFICIENT_CONTEXT:
        return RecurrenceAssessment(
            status=RecurrenceStrength.WEAK,
            confidence=0.3,
            explanation_codes=["insufficient_context_blocks_recurrence"],
        )
    if independence.status == IndependenceStatus.DEPENDENT:
        return RecurrenceAssessment(
            status=RecurrenceStrength.WEAK,
            confidence=0.45,
            supporting_signal_ids=[],
            contradicting_signal_ids=[e.signal.signal_id for e in episodes],
            explanation_codes=["dependent_episodes_cannot_establish_recurrence"],
        )

    supporting: list[str] = []
    contradicting: list[str] = []
    weak_attr = 0
    caller_asserted = 0
    independent_support = 0

    for ep in episodes:
        sig = ep.signal
        attr = sig.attribution_strength
        if ep.observation_provenance == ObservationTimeProvenance.CALLER_ASSERTED:
            caller_asserted += 1
            codes.append("caller_asserted_provenance_present")
        if ep.observation_provenance == ObservationTimeProvenance.UNKNOWN:
            codes.append("unknown_provenance_present")

        if attr in {
            AttributionAssessment.NOT_ASSESSED,
            AttributionAssessment.INSUFFICIENT_EVIDENCE,
            AttributionAssessment.CONFLICTING_EVIDENCE,
        }:
            weak_attr += 1
            codes.append("weak_attribution_episode")
            if sig.ineffective_dimensions and not sig.effective_dimensions:
                contradicting.append(sig.signal_id)
            continue

        if attr == AttributionAssessment.TEMPORAL_ASSOCIATION:
            codes.append("temporal_association_capped")

        if sig.signal_strength == LearningSignalStrength.SUPPORTED and (
            sig.effectiveness.status.value in {"highly_effective", "effective", "counterproductive"}
        ):
            if sig.effectiveness.status.value == "counterproductive" or sig.ineffective_dimensions:
                if "regression" in sig.ineffective_dimensions or sig.effectiveness.status.value == "counterproductive":
                    contradicting.append(sig.signal_id)
                    codes.append("supported_counterexample")
                else:
                    supporting.append(sig.signal_id)
            else:
                supporting.append(sig.signal_id)
                if independence.status == IndependenceStatus.INDEPENDENT:
                    independent_support += 1
        elif sig.signal_strength == LearningSignalStrength.CANDIDATE:
            if sig.effective_dimensions and not sig.ineffective_dimensions:
                supporting.append(sig.signal_id)
            elif sig.ineffective_dimensions:
                contradicting.append(sig.signal_id)
            else:
                codes.append("ambiguous_candidate_excluded_from_counts")
        else:
            codes.append("weak_signal_excluded_from_support")
            if sig.ineffective_dimensions:
                contradicting.append(sig.signal_id)

    supporting = _dedupe(supporting)
    contradicting = _dedupe(contradicting)
    both = set(supporting) & set(contradicting)
    if both:
        supporting = [s for s in supporting if s not in both]
        codes.append("ambiguous_signals_removed_from_support")

    if caller_asserted:
        supporting_eps = [ep for ep in episodes if ep.signal.signal_id in supporting]
        if supporting_eps and all(
            ep.observation_provenance == ObservationTimeProvenance.CALLER_ASSERTED for ep in supporting_eps
        ):
            codes.append("caller_asserted_cannot_create_supported_recurrence")

    supp_n = len(supporting)
    cont_n = len(contradicting)

    if cont_n > 0 and supp_n == 0:
        status = RecurrenceStrength.INVALIDATED
        conf = 0.7
        codes.append("only_counterexamples")
    elif cont_n > 0 and supp_n > 0:
        if cont_n >= supp_n:
            status = RecurrenceStrength.CONTESTED
            conf = 0.65
            codes.append("counterexamples_dominate_or_balance")
        else:
            status = RecurrenceStrength.CONTESTED
            conf = 0.55
            codes.append("supporting_with_visible_counterexamples")
    elif supp_n == 0:
        status = RecurrenceStrength.WEAK
        conf = 0.4
        codes.append("no_supporting_episodes")
    elif independence.status != IndependenceStatus.INDEPENDENT:
        status = RecurrenceStrength.EMERGING
        conf = 0.5
        codes.append("partial_independence_caps_at_emerging")
    elif caller_asserted > 0 and all(
        ep.observation_provenance == ObservationTimeProvenance.CALLER_ASSERTED
        for ep in episodes
        if ep.signal.signal_id in supporting
    ):
        status = RecurrenceStrength.EMERGING
        conf = 0.5
        codes.append("caller_asserted_caps_at_emerging")
    elif weak_attr > 0 and independent_support < 2:
        status = RecurrenceStrength.EMERGING
        conf = 0.5
        codes.append("weak_attribution_caps_strength")
    elif independent_support >= 3 and comparability.status == ComparabilityStatus.COMPARABLE:
        status = RecurrenceStrength.SUPPORTED
        conf = 0.75
        codes.append("independent_comparable_support")
    elif independent_support >= 2 and comparability.status in {
        ComparabilityStatus.COMPARABLE,
        ComparabilityStatus.PARTIALLY_COMPARABLE,
    }:
        status = RecurrenceStrength.EMERGING
        conf = 0.6
        codes.append("emerging_independent_support")
    elif supp_n >= 2:
        status = RecurrenceStrength.EMERGING
        conf = 0.55
        codes.append("emerging_support")
    else:
        status = RecurrenceStrength.WEAK
        conf = 0.4
        codes.append("single_support_insufficient")

    return RecurrenceAssessment(
        status=status,
        confidence=round(conf, 4),
        supporting_signal_ids=supporting,
        contradicting_signal_ids=contradicting,
        supporting_count=supp_n,
        contradicting_count=cont_n,
        independent_supporting_count=independent_support,
        weak_attribution_count=weak_attr,
        caller_asserted_provenance_count=caller_asserted,
        explanation_codes=_dedupe(codes),
    )


def extract_experience_pattern_candidate(
    *,
    episodes: list[ExperienceEpisodeInput],
    comparison: ExperienceComparison,
    recurrence: RecurrenceAssessment,
    pattern_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> ExperiencePatternCandidate:
    """experience_pattern_candidate_v1 — candidate only; is_knowledge/is_policy fixed false."""

    now = evaluated_at or datetime.now(UTC)
    signals = [e.signal for e in episodes]

    scope: list[str] = []
    if comparison.comparability.shared_goal_id:
        scope.append(f"goal_id={comparison.comparability.shared_goal_id}")
    if comparison.comparability.shared_algorithm:
        scope.append(f"algorithm={comparison.comparability.shared_algorithm}")
    if comparison.comparability.shared_fidelity_class:
        scope.append(f"fidelity={comparison.comparability.shared_fidelity_class}")
    for s in signals:
        scope.extend(s.scope_conditions)
    scope = _dedupe(scope)

    invalidation: list[str] = [
        "Any independent counterexample under comparable conditions",
        "Evidence that attribution was mis-specified across the set",
        "Material change in decision algorithm or criteria weights",
        "Loss of independence (duplicate decision_id or evidence lineage)",
    ]
    for s in signals:
        invalidation.extend(s.invalidation_conditions)
    invalidation = _dedupe(invalidation)

    eff_dims = _dedupe([d for s in signals for d in s.effective_dimensions])
    ineff_dims = _dedupe([d for s in signals for d in s.ineffective_dimensions])

    evidence = _dedupe([eid for s in signals for eid in s.supporting_evidence_ids])
    contra_evidence = _dedupe(
        [
            eid
            for s in signals
            if s.signal_id in recurrence.contradicting_signal_ids
            for eid in s.supporting_evidence_ids
        ]
    )

    attr_order = [
        AttributionAssessment.NOT_ASSESSED,
        AttributionAssessment.INSUFFICIENT_EVIDENCE,
        AttributionAssessment.CONFLICTING_EVIDENCE,
        AttributionAssessment.TEMPORAL_ASSOCIATION,
        AttributionAssessment.SUPPORTED_CONTRIBUTION,
    ]
    floor = AttributionAssessment.SUPPORTED_CONTRIBUTION
    for s in signals:
        if s.attribution_strength in attr_order:
            if attr_order.index(s.attribution_strength) < attr_order.index(floor):
                floor = s.attribution_strength

    lesson_parts = [
        f"Across {len(signals)} episodes (supporting={recurrence.supporting_count}, "
        f"contradicting={recurrence.contradicting_count}) recurrence={recurrence.status.value}."
    ]
    if recurrence.status == RecurrenceStrength.SUPPORTED:
        lesson_parts.append(
            "Independent comparable episodes support a candidate pattern; "
            "do not promote to knowledge or policy without further review."
        )
    elif recurrence.status == RecurrenceStrength.CONTESTED:
        lesson_parts.append("Visible counterexamples prevent uncontested recurrence claims.")
    elif recurrence.status == RecurrenceStrength.INVALIDATED:
        lesson_parts.append("Counterexamples without support invalidate the candidate pattern.")
    else:
        lesson_parts.append(
            "Preserve as multi-episode observation; do not promote without stronger independent support."
        )

    subject_refs: list[BusinessObjectRef] = []
    seen_subj: set[str] = set()
    for s in signals:
        for r in s.subject_refs:
            key = _subject_key(r)
            if key not in seen_subj:
                seen_subj.add(key)
                subject_refs.append(r)

    goal_id = comparison.comparability.shared_goal_id or next((s.goal_id for s in signals if s.goal_id), None)

    return ExperiencePatternCandidate(
        pattern_id=pattern_id or f"pat_{uuid4().hex[:12]}",
        comparison_id=comparison.comparison_id,
        signal_ids=[s.signal_id for s in signals],
        decision_ids=_dedupe([s.decision_id for s in signals]),
        subject_refs=subject_refs,
        goal_id=goal_id,
        comparability=comparison.comparability,
        independence=comparison.independence,
        recurrence=recurrence,
        candidate_pattern=" ".join(lesson_parts)[:2000],
        scope_conditions=scope,
        invalidation_conditions=invalidation,
        supporting_evidence_ids=evidence,
        contradicting_evidence_ids=contra_evidence,
        effective_dimensions=eff_dims,
        ineffective_dimensions=ineff_dims,
        attribution_floor=floor,
        evaluated_at=now,
    )


def evaluate_experience_set(
    *,
    episodes: list[ExperienceEpisodeInput],
    result_id: str | None = None,
    comparison_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> ExperienceIntelligenceResult:
    """Compose one multi-episode experience intelligence artifact.

    Comparability and independence are evaluated before any recurrence claim.
    """

    now = evaluated_at or datetime.now(UTC)
    codes: list[str] = []

    if len(episodes) < 2:
        codes.append("fewer_than_two_episodes")

    comparability = assess_experience_comparability(episodes)
    independence = assess_experience_independence(episodes)

    comparison = ExperienceComparison(
        comparison_id=comparison_id or f"cmp_{uuid4().hex[:12]}",
        episode_count=len(episodes),
        signal_ids=[e.signal.signal_id for e in episodes],
        decision_ids=_dedupe([e.signal.decision_id for e in episodes]),
        comparability=comparability,
        independence=independence,
        evaluated_at=now,
        explanation_codes=_dedupe(comparability.explanation_codes[:4] + independence.explanation_codes[:4]),
    )

    recurrence = assess_experience_recurrence(
        episodes=episodes,
        comparability=comparability,
        independence=independence,
    )

    pattern: ExperiencePatternCandidate | None = None
    if len(episodes) >= 2 and comparability.status != ComparabilityStatus.NOT_COMPARABLE:
        pattern = extract_experience_pattern_candidate(
            episodes=episodes,
            comparison=comparison,
            recurrence=recurrence,
            evaluated_at=now,
        )
    else:
        codes.append("pattern_candidate_suppressed")

    return ExperienceIntelligenceResult(
        result_id=result_id or f"exp_{uuid4().hex[:12]}",
        comparison=comparison,
        pattern_candidate=pattern,
        evaluated_at=now,
        explanation_codes=_dedupe(codes + recurrence.explanation_codes[:3]),
    )
