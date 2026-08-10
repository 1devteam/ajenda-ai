"""Adversarial contracts for Experience Intelligence Slice 1.

Aligned to multi-candidate Experience Equivalence & Recurrence Eligibility Contract:
- recommendation_class hard-required for recurrence eligibility
- subject type = semantic class; instance = independence only
- goal_id strongest; typed objective dimensions allow PARTIAL (EMERGING max)
- pattern_candidates list (zero / one / many); comparison is first eligible surface
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.services.ontology.decision_feedback import (
    ConfidenceCalibrationAssessment,
    ConfidenceCalibrationStatus,
    ConsequenceInventory,
    DecisionEffectivenessEvaluation,
    DecisionEffectivenessStatus,
    DecisionLearningSignal,
    DecisionQualityAssessment,
    DecisionQualityStatus,
    EffectivenessDimensions,
    ExecutionFidelity,
    LearningSignalStrength,
)
from backend.services.ontology.experience_intelligence import (
    ComparabilityStatus,
    ExperienceEpisodeInput,
    ExperiencePatternCandidate,
    IndependenceStatus,
    RecurrenceStrength,
    evaluate_experience_set,
)
from backend.services.ontology.observation_attribution import (
    AttributionAssessment,
    ObservationTimeProvenance,
)
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation

EVALUATED_AT = datetime(2026, 8, 9, 12, tzinfo=UTC)


def _quality(
    status: DecisionQualityStatus = DecisionQualityStatus.WELL_SUPPORTED,
) -> DecisionQualityAssessment:
    return DecisionQualityAssessment(
        status=status,
        confidence=0.8,
        alternatives_compared=True,
        confidence_consistent_with_evidence=True,
    )


def _effectiveness(
    status: DecisionEffectivenessStatus = DecisionEffectivenessStatus.HIGHLY_EFFECTIVE,
    *,
    attribution: AttributionAssessment = AttributionAssessment.SUPPORTED_CONTRIBUTION,
    fidelity: ExecutionFidelity = ExecutionFidelity.EXECUTED_AS_RECOMMENDED,
) -> DecisionEffectivenessEvaluation:
    return DecisionEffectivenessEvaluation(
        status=status,
        confidence=0.8,
        dimensions=EffectivenessDimensions(
            goal_progress=(
                "achieved"
                if status == DecisionEffectivenessStatus.HIGHLY_EFFECTIVE
                else "regressed"
            ),
            execution_fidelity=fidelity,
            attribution_strength=attribution,
            regression_observed=status == DecisionEffectivenessStatus.COUNTERPRODUCTIVE,
        ),
    )


def _calibration() -> ConfidenceCalibrationAssessment:
    return ConfidenceCalibrationAssessment(
        status=ConfidenceCalibrationStatus.WELL_CALIBRATED,
        original_confidence=0.8,
    )


def _signal(
    *,
    signal_id: str,
    decision_id: str,
    goal_id: str | None = "goal_1",
    subject_id: str = "opp_1",
    strength: LearningSignalStrength = LearningSignalStrength.SUPPORTED,
    attribution: AttributionAssessment = AttributionAssessment.SUPPORTED_CONTRIBUTION,
    effectiveness: DecisionEffectivenessStatus = DecisionEffectivenessStatus.HIGHLY_EFFECTIVE,
    effective_dims: list[str] | None = None,
    ineffective_dims: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    fidelity: ExecutionFidelity = ExecutionFidelity.EXECUTED_AS_RECOMMENDED,
) -> DecisionLearningSignal:
    return DecisionLearningSignal(
        signal_id=signal_id,
        decision_id=decision_id,
        subject_refs=[{"object_type": "opportunity", "object_id": subject_id}],
        goal_id=goal_id,
        decision_quality=_quality(),
        execution_fidelity=fidelity,
        effectiveness=_effectiveness(
            effectiveness, attribution=attribution, fidelity=fidelity
        ),
        confidence_calibration=_calibration(),
        evidence_gaps_at_decision_time=[],
        information_learned_after_decision=[],
        effective_dimensions=effective_dims
        or (
            ["goal_progress"]
            if effectiveness != DecisionEffectivenessStatus.COUNTERPRODUCTIVE
            else []
        ),
        ineffective_dimensions=ineffective_dims
        or (
            ["regression"]
            if effectiveness == DecisionEffectivenessStatus.COUNTERPRODUCTIVE
            else []
        ),
        consequences=ConsequenceInventory(),
        attribution_strength=attribution,
        candidate_lesson=f"Episode {signal_id}",
        scope_conditions=[f"goal_id={goal_id}" if goal_id else "goal_unscoped"],
        invalidation_conditions=["Repeated counterexamples under comparable conditions"],
        supporting_evidence_ids=evidence_ids or [f"ev_{signal_id}"],
        signal_strength=strength,
        evaluated_at=EVALUATED_AT,
    )


def _episode(
    signal: DecisionLearningSignal,
    *,
    provenance: ObservationTimeProvenance | None = ObservationTimeProvenance.SOURCE_VERIFIED,
    algorithm: str | None = "weighted_criterion_evidence_v1@1",
    rec_class: str | None = "option_a",
) -> ExperienceEpisodeInput:
    return ExperienceEpisodeInput(
        signal=signal,
        observation_provenance=provenance,
        attribution_earned=True,
        decision_algorithm=algorithm,
        recommendation_class=rec_class,
    )


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )


def _first_candidate(result):
    assert result.pattern_candidates, "expected at least one pattern candidate"
    return result.pattern_candidates[0]


def test_two_independent_supported_episodes_can_emerge() -> None:
    episodes = [
        _episode(_signal(signal_id="s1", decision_id="d1", evidence_ids=["e1"])),
        _episode(_signal(signal_id="s2", decision_id="d2", evidence_ids=["e2"])),
    ]
    result = evaluate_experience_set(episodes=episodes)

    assert result.comparison is not None
    assert result.comparison.comparability.status == ComparabilityStatus.COMPARABLE
    assert result.comparison.independence.status == IndependenceStatus.INDEPENDENT
    cand = _first_candidate(result)
    assert cand.recurrence.status in {
        RecurrenceStrength.EMERGING,
        RecurrenceStrength.SUPPORTED,
    }
    assert cand.is_knowledge is False
    assert cand.is_policy is False


def test_three_independent_comparable_support_can_reach_supported() -> None:
    episodes = [
        _episode(_signal(signal_id="s1", decision_id="d1", evidence_ids=["e1"])),
        _episode(_signal(signal_id="s2", decision_id="d2", evidence_ids=["e2"])),
        _episode(_signal(signal_id="s3", decision_id="d3", evidence_ids=["e3"])),
    ]
    result = evaluate_experience_set(episodes=episodes)
    cand = _first_candidate(result)
    assert cand.recurrence.status == RecurrenceStrength.SUPPORTED
    assert cand.recurrence.independent_supporting_count >= 3


def test_foreign_goal_is_not_comparable() -> None:
    episodes = [
        _episode(_signal(signal_id="s1", decision_id="d1", goal_id="goal_a")),
        _episode(_signal(signal_id="s2", decision_id="d2", goal_id="goal_b")),
    ]
    result = evaluate_experience_set(episodes=episodes)
    assert result.pattern_candidates == []
    assert result.comparison is not None
    assert result.comparison.comparability.status == ComparabilityStatus.NOT_COMPARABLE
    assert "foreign_goal_rejected" in result.comparison.comparability.explanation_codes


def test_same_subject_type_different_instances_remain_comparable() -> None:
    """Subject type is semantic class; instance id is independence only."""
    episodes = [
        _episode(_signal(signal_id="s1", decision_id="d1", subject_id="opp_a")),
        _episode(_signal(signal_id="s2", decision_id="d2", subject_id="opp_b")),
    ]
    result = evaluate_experience_set(episodes=episodes)
    assert result.comparison is not None
    assert result.comparison.comparability.status in {
        ComparabilityStatus.COMPARABLE,
        ComparabilityStatus.PARTIALLY_COMPARABLE,
    }
    assert result.comparison.independence.status == IndependenceStatus.INDEPENDENT
    assert result.pattern_candidates


def test_duplicate_decision_id_is_dependent_and_weak() -> None:
    episodes = [
        _episode(_signal(signal_id="s1", decision_id="same_decision")),
        _episode(_signal(signal_id="s2", decision_id="same_decision")),
    ]
    result = evaluate_experience_set(episodes=episodes)
    assert result.comparison is not None
    assert result.comparison.independence.status == IndependenceStatus.DEPENDENT
    cand = _first_candidate(result)
    assert cand.recurrence.status == RecurrenceStrength.WEAK
    assert "dependent_episodes_cannot_establish_recurrence" in cand.recurrence.explanation_codes


def test_overlapping_evidence_reduces_independence() -> None:
    episodes = [
        _episode(_signal(signal_id="s1", decision_id="d1", evidence_ids=["shared", "e1"])),
        _episode(_signal(signal_id="s2", decision_id="d2", evidence_ids=["shared", "e2"])),
    ]
    result = evaluate_experience_set(episodes=episodes)
    assert result.comparison is not None
    assert result.comparison.independence.status == IndependenceStatus.PARTIALLY_INDEPENDENT
    assert "shared" in result.comparison.independence.overlapping_evidence_ids


def test_counterexample_makes_recurrence_contested() -> None:
    positive = _signal(signal_id="s1", decision_id="d1", evidence_ids=["e1"])
    negative = _signal(
        signal_id="s2",
        decision_id="d2",
        evidence_ids=["e2"],
        effectiveness=DecisionEffectivenessStatus.COUNTERPRODUCTIVE,
        ineffective_dims=["regression"],
        effective_dims=[],
    )
    episodes = [_episode(positive), _episode(negative)]
    result = evaluate_experience_set(episodes=episodes)
    cand = _first_candidate(result)
    assert cand.recurrence.status == RecurrenceStrength.CONTESTED
    assert cand.recurrence.contradicting_count >= 1
    assert cand.recurrence.supporting_count >= 1


def test_only_counterexamples_invalidates() -> None:
    episodes = [
        _episode(
            _signal(
                signal_id="s1",
                decision_id="d1",
                evidence_ids=["e1"],
                effectiveness=DecisionEffectivenessStatus.COUNTERPRODUCTIVE,
                ineffective_dims=["regression"],
                effective_dims=[],
            )
        ),
        _episode(
            _signal(
                signal_id="s2",
                decision_id="d2",
                evidence_ids=["e2"],
                effectiveness=DecisionEffectivenessStatus.COUNTERPRODUCTIVE,
                ineffective_dims=["regression"],
                effective_dims=[],
            )
        ),
    ]
    result = evaluate_experience_set(episodes=episodes)
    cand = _first_candidate(result)
    assert cand.recurrence.status == RecurrenceStrength.INVALIDATED


def test_caller_asserted_provenance_cannot_create_supported_recurrence() -> None:
    episodes = [
        _episode(
            _signal(signal_id="s1", decision_id="d1", evidence_ids=["e1"]),
            provenance=ObservationTimeProvenance.CALLER_ASSERTED,
        ),
        _episode(
            _signal(signal_id="s2", decision_id="d2", evidence_ids=["e2"]),
            provenance=ObservationTimeProvenance.CALLER_ASSERTED,
        ),
        _episode(
            _signal(signal_id="s3", decision_id="d3", evidence_ids=["e3"]),
            provenance=ObservationTimeProvenance.CALLER_ASSERTED,
        ),
    ]
    result = evaluate_experience_set(episodes=episodes)
    cand = _first_candidate(result)
    assert cand.recurrence.status != RecurrenceStrength.SUPPORTED
    assert cand.recurrence.status in {
        RecurrenceStrength.EMERGING,
        RecurrenceStrength.WEAK,
    }
    codes = cand.recurrence.explanation_codes
    assert (
        "caller_asserted_caps_at_emerging" in codes
        or "caller_asserted_cannot_create_supported_recurrence" in codes
    )


def test_weak_attribution_does_not_inflate_recurrence() -> None:
    episodes = [
        _episode(
            _signal(
                signal_id="s1",
                decision_id="d1",
                evidence_ids=["e1"],
                attribution=AttributionAssessment.INSUFFICIENT_EVIDENCE,
                strength=LearningSignalStrength.WEAK,
            )
        ),
        _episode(
            _signal(
                signal_id="s2",
                decision_id="d2",
                evidence_ids=["e2"],
                attribution=AttributionAssessment.NOT_ASSESSED,
                strength=LearningSignalStrength.WEAK,
            )
        ),
    ]
    result = evaluate_experience_set(episodes=episodes)
    cand = _first_candidate(result)
    assert cand.recurrence.status == RecurrenceStrength.WEAK
    assert cand.recurrence.supporting_count == 0


def test_single_episode_is_insufficient() -> None:
    episodes = [_episode(_signal(signal_id="s1", decision_id="d1"))]
    result = evaluate_experience_set(episodes=episodes)
    assert result.pattern_candidates == []
    if result.comparison is not None:
        assert result.comparison.comparability.status in {
            ComparabilityStatus.INSUFFICIENT_CONTEXT,
            ComparabilityStatus.NOT_COMPARABLE,
        }


def test_missing_recommendation_class_hard_excludes() -> None:
    episodes = [
        _episode(
            _signal(signal_id="s1", decision_id="d1", evidence_ids=["e1"]),
            rec_class=None,
        ),
        _episode(
            _signal(signal_id="s2", decision_id="d2", evidence_ids=["e2"]),
            rec_class=None,
        ),
    ]
    result = evaluate_experience_set(episodes=episodes)
    assert result.pattern_candidates == []
    assert "s1" in result.unclassified_episode_ids
    assert "s2" in result.unclassified_episode_ids


def test_heterogeneous_recommendation_classes_produce_separate_partitions() -> None:
    episodes = [
        _episode(
            _signal(signal_id="s1", decision_id="d1", evidence_ids=["e1"]),
            rec_class="option_a",
        ),
        _episode(
            _signal(signal_id="s2", decision_id="d2", evidence_ids=["e2"]),
            rec_class="option_a",
        ),
        _episode(
            _signal(signal_id="s3", decision_id="d3", evidence_ids=["e3"]),
            rec_class="option_b",
        ),
        _episode(
            _signal(signal_id="s4", decision_id="d4", evidence_ids=["e4"]),
            rec_class="option_b",
        ),
    ]
    result = evaluate_experience_set(episodes=episodes)
    assert len(result.pattern_candidates) == 2
    classes = {c.recommendation_class for c in result.pattern_candidates}
    assert classes == {"option_a", "option_b"}


def test_pattern_flags_cannot_be_overridden() -> None:
    episodes = [
        _episode(_signal(signal_id="s1", decision_id="d1", evidence_ids=["e1"])),
        _episode(_signal(signal_id="s2", decision_id="d2", evidence_ids=["e2"])),
    ]
    result = evaluate_experience_set(episodes=episodes)
    cand = _first_candidate(result)
    payload = cand.model_dump(mode="json")
    payload["is_knowledge"] = True
    with pytest.raises(ValidationError):
        ExperiencePatternCandidate.model_validate(payload)


def test_pattern_flags_are_immutable() -> None:
    episodes = [
        _episode(_signal(signal_id="s1", decision_id="d1", evidence_ids=["e1"])),
        _episode(_signal(signal_id="s2", decision_id="d2", evidence_ids=["e2"])),
    ]
    result = evaluate_experience_set(episodes=episodes)
    cand = _first_candidate(result)
    with pytest.raises(ValidationError):
        cand.is_knowledge = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "action",
    [
        "analysis.compare_experiences",
        "analysis.assess_experience_recurrence",
    ],
)
def test_experience_actions_are_registered_and_evidence_backed(action: str) -> None:
    registry = get_default_action_registry(rebuild=True)
    definition = registry.get(action)
    episodes = [
        _episode(_signal(signal_id="s1", decision_id="d1", evidence_ids=["e1"])),
        _episode(_signal(signal_id="s2", decision_id="d2", evidence_ids=["e2"])),
    ]
    invocation = ToolInvocation(
        action=action,
        input={"episodes": [e.model_dump(mode="json") for e in episodes]},
    )
    result = registry.invoke(invocation, _context())
    assert definition.side_effect_class.value == "none"
    assert result.side_effect_class.value == "none"
    assert result.evidence
    if action == "analysis.assess_experience_recurrence":
        output = result.output
        if "pattern_candidates" in output:
            for cand in output["pattern_candidates"]:
                assert cand.get("is_knowledge") is False
                assert cand.get("is_policy") is False
        else:
            assert output.get("is_knowledge") is False
