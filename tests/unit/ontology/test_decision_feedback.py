"""Adversarial contracts for Decision Feedback Intelligence Slice 1."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.services.ontology.decision_feedback import (
    DecisionEffectivenessStatus,
    DecisionExecutionObservation,
    DecisionLearningSignal,
    DecisionQualityStatus,
    DecisionSnapshot,
    ExecutionFidelity,
    LearningSignalStrength,
    evaluate_decision_feedback,
)
from backend.services.ontology.observation_attribution import (
    AttributionEvidenceInput,
    evaluate_attribution_evidence,
    resolve_observation_timing,
)
from backend.services.ontology.outcome import (
    AttributionAssessment,
    OutcomeEvaluation,
    OutcomeStatus,
)
from backend.services.tools.action_registry import get_default_action_registry

DECIDED_AT = datetime(2026, 8, 1, 9, tzinfo=UTC)
EXECUTED_AT = datetime(2026, 8, 2, 9, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 8, 3, 9, tzinfo=UTC)
EVALUATED_AT = datetime(2026, 8, 4, 9, tzinfo=UTC)


def _score_row(
    option_id: str,
    *,
    dimension_status: str = "known",
    dimension_score: float = 1.0,
    total_score: float = 0.9,
) -> dict[str, object]:
    return {
        "option_id": option_id,
        "total_score": total_score,
        "feasible": True,
        "dimension_scores": [
            {
                "criterion_id": "fit",
                "status": dimension_status,
                "score": dimension_score,
            }
        ],
        "missing_criterion_ids": [],
        "gaps": [],
    }


def _snapshot(*, recommendation: str = "option_a", weak: bool = False) -> DecisionSnapshot:
    chosen = _score_row(
        "option_a",
        dimension_status="unsupported" if weak else "known",
        dimension_score=0.0 if weak else 1.0,
    )
    return DecisionSnapshot(
        decision_id="decision_1",
        goal_id="goal_1",
        subject_refs=[{"object_type": "opportunity", "object_id": "opp_1"}],
        recommendation=recommendation,
        alternatives_considered=["option_b"],
        option_scores=[chosen, _score_row("option_b", total_score=0.5)],
        original_confidence=0.8,
        supporting_evidence_ids=["decision_evidence"],
        decided_at=DECIDED_AT,
    )


def _execution(
    fidelity: ExecutionFidelity = ExecutionFidelity.EXECUTED_AS_RECOMMENDED,
    *,
    executed_at: datetime | None = EXECUTED_AT,
) -> DecisionExecutionObservation:
    return DecisionExecutionObservation(
        fidelity=fidelity,
        executed_at=executed_at,
        execution_evidence_ids=["execution_evidence"],
        material_variations=["changed channel"]
        if fidelity == ExecutionFidelity.EXECUTED_WITH_MATERIAL_VARIATION
        else [],
    )


def _outcome(
    *,
    status: OutcomeStatus = OutcomeStatus.ACHIEVED,
    attribution: AttributionAssessment = AttributionAssessment.SUPPORTED_CONTRIBUTION,
    observed_at: datetime | None = OBSERVED_AT,
    evaluated_at: datetime = EVALUATED_AT,
) -> OutcomeEvaluation:
    timing = resolve_observation_timing(source_observed_at=observed_at)
    attribution_evidence = None
    if attribution == AttributionAssessment.SUPPORTED_CONTRIBUTION:
        attribution_evidence = evaluate_attribution_evidence(
            evidence=AttributionEvidenceInput(
                executed_at=EXECUTED_AT,
                execution_evidence_ids=["execution_evidence"],
                expected_change_dimensions=["qualification_score"],
                observed_change_dimensions=["qualification_score"],
                confidence=0.9,
            ),
            observation_timing=timing,
        )
        attribution = attribution_evidence.resulting_attribution
    return OutcomeEvaluation(
        outcome_evaluation_id="outcome_1",
        subject_refs=[{"object_type": "opportunity", "object_id": "opp_1"}],
        goal_id="goal_1",
        status=status,
        attribution=attribution,
        attribution_evidence=attribution_evidence,
        confidence=0.9,
        supporting_evidence_ids=["outcome_evidence"],
        observed_at=observed_at,
        observation_timing=timing,
        evaluated_at=evaluated_at,
    )


def test_exact_supported_episode_can_be_highly_effective() -> None:
    result = evaluate_decision_feedback(
        snapshot=_snapshot(),
        execution=_execution(),
        outcome=_outcome(),
    )

    assert result.quality.status == DecisionQualityStatus.WELL_SUPPORTED
    assert result.effectiveness.status == DecisionEffectivenessStatus.HIGHLY_EFFECTIVE
    assert result.learning_signal.signal_strength == LearningSignalStrength.SUPPORTED


def test_unsupported_decision_lucky_outcome_is_capped() -> None:
    result = evaluate_decision_feedback(
        snapshot=_snapshot(weak=True),
        execution=_execution(),
        outcome=_outcome(),
    )

    assert result.quality.status == DecisionQualityStatus.UNSUPPORTED
    assert result.effectiveness.status == DecisionEffectivenessStatus.PARTIALLY_EFFECTIVE
    assert result.effectiveness.status != DecisionEffectivenessStatus.HIGHLY_EFFECTIVE
    assert "weak_decision_lucky_outcome_not_great_decision" in result.effectiveness.explanation_codes


def test_recommendation_absent_from_scores_fails_closed() -> None:
    result = evaluate_decision_feedback(
        snapshot=_snapshot(recommendation="missing_option"),
        execution=_execution(),
        outcome=_outcome(),
    )

    assert result.quality.status == DecisionQualityStatus.INCONCLUSIVE
    assert result.quality.required_criteria_supported_ratio is None
    assert "selected_option_not_found" in result.quality.explanation_codes
    assert result.effectiveness.status == DecisionEffectivenessStatus.NOT_EVALUABLE


def test_impossible_outcome_chronology_fails_closed() -> None:
    result = evaluate_decision_feedback(
        snapshot=_snapshot(),
        execution=_execution(),
        outcome=_outcome(observed_at=datetime(2026, 8, 2, 8, tzinfo=UTC)),
    )

    assert result.effectiveness.status == DecisionEffectivenessStatus.NOT_EVALUABLE
    assert "outcome_observation_precedes_execution" in result.effectiveness.explanation_codes
    assert result.learning_signal.signal_strength == LearningSignalStrength.WEAK


def test_execution_before_decision_is_rejected() -> None:
    with pytest.raises(ValueError, match="execution cannot precede decision"):
        evaluate_decision_feedback(
            snapshot=_snapshot(),
            execution=_execution(executed_at=datetime(2026, 8, 1, 8, tzinfo=UTC)),
            outcome=_outcome(),
        )


def test_unknown_outcome_chronology_does_not_create_supported_signal() -> None:
    result = evaluate_decision_feedback(
        snapshot=_snapshot(),
        execution=_execution(),
        outcome=_outcome(observed_at=None),
    )

    assert result.effectiveness.status == DecisionEffectivenessStatus.NOT_EVALUABLE
    assert "outcome_observation_time_unknown" in result.effectiveness.explanation_codes
    assert result.learning_signal.signal_strength == LearningSignalStrength.WEAK


def test_evaluation_time_is_not_used_as_outcome_observation_time() -> None:
    result = evaluate_decision_feedback(
        snapshot=_snapshot(),
        execution=_execution(),
        outcome=_outcome(
            observed_at=OBSERVED_AT,
            evaluated_at=datetime(2026, 8, 1, 8, tzinfo=UTC),
        ),
    )

    assert result.effectiveness.status == DecisionEffectivenessStatus.HIGHLY_EFFECTIVE
    assert "outcome_observation_precedes_execution" not in result.explanation_codes


def test_post_decision_information_cannot_improve_quality() -> None:
    baseline = evaluate_decision_feedback(
        snapshot=_snapshot(weak=True),
        execution=_execution(),
        outcome=_outcome(),
    )
    hindsight = evaluate_decision_feedback(
        snapshot=_snapshot(weak=True),
        execution=_execution(),
        outcome=_outcome(),
        information_learned_after=["later evidence strongly supported option_a"],
    )

    assert hindsight.quality == baseline.quality
    assert "post_decision_information_excluded_from_quality" in hindsight.explanation_codes


def test_material_variation_cannot_evaluate_original_recommendation() -> None:
    result = evaluate_decision_feedback(
        snapshot=_snapshot(),
        execution=_execution(ExecutionFidelity.EXECUTED_WITH_MATERIAL_VARIATION),
        outcome=_outcome(),
    )

    assert result.effectiveness.status == DecisionEffectivenessStatus.NOT_EVALUABLE
    assert "material_variation_blocks_direct_recommendation_evaluation" in (result.effectiveness.explanation_codes)


def test_partial_execution_with_weak_attribution_does_not_overstate_effectiveness() -> None:
    result = evaluate_decision_feedback(
        snapshot=_snapshot(),
        execution=_execution(ExecutionFidelity.PARTIALLY_EXECUTED),
        outcome=_outcome(attribution=AttributionAssessment.TEMPORAL_ASSOCIATION),
    )

    assert result.effectiveness.status == DecisionEffectivenessStatus.NOT_EVALUABLE
    assert "partial_execution_with_weak_attribution_not_evaluable" in (result.effectiveness.explanation_codes)
    assert result.learning_signal.signal_strength == LearningSignalStrength.WEAK


def test_supported_counterproductive_episode_is_observation_not_knowledge() -> None:
    result = evaluate_decision_feedback(
        snapshot=_snapshot(),
        execution=_execution(),
        outcome=_outcome(status=OutcomeStatus.REGRESSED),
    )

    assert result.effectiveness.status == DecisionEffectivenessStatus.COUNTERPRODUCTIVE
    assert result.learning_signal.signal_strength == LearningSignalStrength.SUPPORTED
    assert result.learning_signal.is_knowledge is False
    assert result.learning_signal.is_policy is False


@pytest.mark.parametrize("field", ["is_knowledge", "is_policy"])
def test_learning_signal_flags_cannot_be_overridden_during_deserialization(field: str) -> None:
    signal = evaluate_decision_feedback(
        snapshot=_snapshot(),
        execution=_execution(),
        outcome=_outcome(),
    ).learning_signal
    payload = signal.model_dump(mode="json")
    payload[field] = True

    with pytest.raises(ValidationError):
        DecisionLearningSignal.model_validate(payload)


def test_learning_signal_flags_are_immutable_after_creation() -> None:
    signal = evaluate_decision_feedback(
        snapshot=_snapshot(),
        execution=_execution(),
        outcome=_outcome(),
    ).learning_signal

    with pytest.raises(ValidationError):
        signal.is_knowledge = True  # type: ignore[misc]
    with pytest.raises(ValidationError):
        signal.is_policy = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "action",
    ["analysis.evaluate_decision_effectiveness", "analysis.extract_decision_learning_signal"],
)
def test_caller_authored_decision_feedback_actions_are_not_production_registered(action: str) -> None:
    registry = get_default_action_registry(rebuild=True)
    with pytest.raises(ValueError, match="unknown action"):
        registry.get(action)
