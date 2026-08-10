from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
from backend.services.ontology.outcome import AttributionAssessment
from backend.services.ontology.types import BusinessObjectRef, BusinessObjectType
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, SideEffectClass, ToolInvocation


def signal(
    i: int,
    *,
    subject_type=BusinessObjectType.OPPORTUNITY,
    subject_id=None,
    goal="goal-a",
    status=DecisionEffectivenessStatus.EFFECTIVE,
    attr=AttributionAssessment.SUPPORTED_CONTRIBUTION,
    signal_id=None,
    decision_id=None,
    evidence=None,
) -> DecisionLearningSignal:
    now = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i)
    return DecisionLearningSignal(
        signal_id=signal_id or f"sig-{i}",
        decision_id=decision_id or f"dec-{i}",
        subject_refs=[BusinessObjectRef(object_type=subject_type, object_id=subject_id or f"obj-{i}")],
        goal_id=goal,
        decision_quality=DecisionQualityAssessment(
            status=DecisionQualityStatus.WELL_SUPPORTED, confidence=0.9, confidence_consistent_with_evidence=True
        ),
        execution_fidelity=ExecutionFidelity.EXECUTED_AS_RECOMMENDED,
        effectiveness=DecisionEffectivenessEvaluation(
            status=status,
            confidence=0.8,
            dimensions=EffectivenessDimensions(
                execution_fidelity=ExecutionFidelity.EXECUTED_AS_RECOMMENDED, attribution_strength=attr
            ),
        ),
        confidence_calibration=ConfidenceCalibrationAssessment(
            status=ConfidenceCalibrationStatus.WELL_CALIBRATED, original_confidence=0.8
        ),
        consequences=ConsequenceInventory(),
        attribution_strength=attr,
        supporting_evidence_ids=evidence or [f"ev-{i}"],
        signal_strength=LearningSignalStrength.SUPPORTED,
        evaluated_at=now,
        effective_dimensions=["conversion"],
        scope_conditions=["smb"],
    )


def ep(i: int, **kw) -> ExperienceEpisodeInput:
    rec = kw.pop("recommendation_class", "discount_offer")
    return ExperienceEpisodeInput(
        episode_id=f"ep-{i}",
        signal=signal(i, **kw),
        recommendation_class=rec,
        objective_dimensions=("increase_conversion",),
        observation_time_provenance="source_verified",
    )


def strengths(result):
    return [c.recurrence.strength for c in result.pattern_candidates]


def test_same_subject_type_different_instances_comparable_and_supported() -> None:
    result = evaluate_experience_set([ep(1), ep(2), ep(3)])
    assert result.comparisons[0].comparability == ComparabilityStatus.COMPARABLE
    assert result.comparisons[0].independence == IndependenceStatus.INDEPENDENT
    assert strengths(result) == [RecurrenceStrength.SUPPORTED]


def test_different_subject_types_and_recommendations_partition_or_block() -> None:
    result = evaluate_experience_set(
        [ep(1), ep(2, subject_type=BusinessObjectType.ACCOUNT), ep(3, recommendation_class="email_nudge")]
    )
    assert any(c.comparability == ComparabilityStatus.INCOMPATIBLE for c in result.comparisons)
    assert len(result.pattern_candidates) == 3


def test_same_exact_subject_instance_surfaces_dependence_not_stronger_support() -> None:
    result = evaluate_experience_set([ep(1, subject_id="same"), ep(2, subject_id="same"), ep(3, subject_id="same")])
    candidate = result.pattern_candidates[0]
    assert candidate.dependent_episode_groups
    assert candidate.recurrence.strength != RecurrenceStrength.SUPPORTED


def test_goal_semantics_do_not_collapse_through_prose_or_status() -> None:
    result = evaluate_experience_set([ep(1, goal="goal-a"), ep(2, goal="goal-b")])
    assert result.comparisons[0].comparability == ComparabilityStatus.INCOMPATIBLE
    partial = evaluate_experience_set([ep(1, goal=None), ep(2, goal=None)])
    assert partial.comparisons[0].comparability == ComparabilityStatus.COMPARABLE


def test_missing_recommendation_class_is_unclassified_not_unknown_partition() -> None:
    result = evaluate_experience_set([ep(1, recommendation_class=None), ep(2, recommendation_class=None)])
    assert result.unclassified_episode_ids == ("ep-1", "ep-2")
    assert result.pattern_candidates == ()
    assert "unknown" not in repr(result.partition_explanations).lower()


def test_duplicate_signal_decision_and_overlap_do_not_increase_support() -> None:
    result = evaluate_experience_set(
        [
            ep(1, signal_id="same-signal"),
            ep(2, signal_id="same-signal"),
            ep(3, decision_id="same-decision"),
            ep(4, decision_id="same-decision"),
            ep(5, evidence=["shared"]),
            ep(6, evidence=["shared"]),
        ]
    )
    candidate = result.pattern_candidates[0]
    assert candidate.recurrence.independence in {IndependenceStatus.DEPENDENT, IndependenceStatus.PARTIALLY_INDEPENDENT}
    assert candidate.recurrence.strength != RecurrenceStrength.SUPPORTED


def test_weak_and_caller_asserted_attribution_caps_supported() -> None:
    result = evaluate_experience_set(
        [
            ep(1, attr=AttributionAssessment.TEMPORAL_ASSOCIATION),
            ep(2, attr=AttributionAssessment.TEMPORAL_ASSOCIATION),
            ep(3, attr=AttributionAssessment.TEMPORAL_ASSOCIATION),
        ]
    )
    assert result.pattern_candidates[0].recurrence.strength != RecurrenceStrength.SUPPORTED
    assert result.pattern_candidates[0].recurrence.attribution_cap is not None


def test_counterexamples_are_partition_local_contested_and_invalidated() -> None:
    contested = evaluate_experience_set([ep(1), ep(2, status=DecisionEffectivenessStatus.INEFFECTIVE)])
    assert contested.pattern_candidates[0].recurrence.strength == RecurrenceStrength.CONTESTED
    invalidated = evaluate_experience_set(
        [
            ep(1, status=DecisionEffectivenessStatus.INEFFECTIVE),
            ep(2, status=DecisionEffectivenessStatus.COUNTERPRODUCTIVE),
        ]
    )
    assert invalidated.pattern_candidates[0].recurrence.strength == RecurrenceStrength.INVALIDATED
    mixed = evaluate_experience_set(
        [ep(1), ep(2, subject_type=BusinessObjectType.ACCOUNT, status=DecisionEffectivenessStatus.INEFFECTIVE)]
    )
    assert all(c.recurrence.strength != RecurrenceStrength.CONTESTED for c in mixed.pattern_candidates)


def test_candidate_safety_flags_are_immutable_and_not_overridable() -> None:
    result = evaluate_experience_set([ep(1), ep(2)])
    candidate = result.pattern_candidates[0]
    assert candidate.is_knowledge is False and candidate.is_policy is False
    with pytest.raises(ValidationError):
        ExperiencePatternCandidate.model_validate({**candidate.model_dump(), "is_knowledge": True})
    with pytest.raises(ValidationError):
        candidate.is_policy = True  # type: ignore[misc]


def test_action_registry_experience_actions_have_evidence_and_no_side_effects() -> None:
    registry = get_default_action_registry(rebuild=True)
    ctx = ActionRuntimeContext(tenant_id="t", task_id=uuid4(), worker_id="w", lease_id="l")
    payload = {"episodes": [ep(1).model_dump(mode="json"), ep(2).model_dump(mode="json")]}
    for action in ("analysis.compare_experiences", "analysis.assess_experience_recurrence"):
        definition = registry.get(action)
        assert definition.side_effect_class == SideEffectClass.NONE
        result = registry.invoke(ToolInvocation(action=action, input=payload), ctx)
        assert result.side_effect_class == SideEffectClass.NONE
        assert result.evidence and result.evidence[0].evidence_type == "action_result_evidence"
