"""Adversarial contracts for Observation & Attribution Integrity Slice 1."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.services.ontology.commercial_state import Goal, Kpi
from backend.services.ontology.observation_attribution import (
    AttributionAssessment,
    AttributionAssessmentEvidence,
    AttributionEvidenceInput,
    AttributionOrdering,
    ObservationTimeProvenance,
    evaluate_attribution_evidence,
    resolve_observation_timing,
)
from backend.services.ontology.outcome import (
    ObservedOutcome,
    OutcomeEvaluation,
    OutcomeExpectation,
    OutcomeStatus,
    evaluate_outcome,
)
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation

EXECUTED_AT = datetime(2026, 8, 2, 9, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 8, 3, 9, tzinfo=UTC)
CAPTURED_AT = datetime(2026, 8, 3, 10, tzinfo=UTC)
ASSERTED_AT = datetime(2026, 8, 3, 11, tzinfo=UTC)


def _evidence(**overrides: object) -> AttributionEvidenceInput:
    payload: dict[str, object] = {
        "executed_at": EXECUTED_AT,
        "execution_evidence_ids": ["execution_event_1"],
        "expected_change_dimensions": ["qualification_score"],
        "observed_change_dimensions": ["qualification_score"],
        "confidence": 0.85,
    }
    payload.update(overrides)
    return AttributionEvidenceInput.model_validate(payload)


def _expectation() -> OutcomeExpectation:
    goal = Goal(goal_id="goal_1", name="Qualify")
    return OutcomeExpectation(
        goal=goal,
        baseline_kpis=[
            Kpi(
                kpi_id="score",
                goal_id="goal_1",
                name="Score",
                metric="qualification_score",
                current_value=60,
                target_value=80,
            )
        ],
    )


def _observed(**overrides: object) -> ObservedOutcome:
    payload: dict[str, object] = {
        "observed_kpis": [
            Kpi(
                kpi_id="score",
                goal_id="goal_1",
                name="Score",
                metric="qualification_score",
                current_value=75,
                target_value=80,
            )
        ],
        "source_observed_at": OBSERVED_AT,
    }
    payload.update(overrides)
    return ObservedOutcome.model_validate(payload)


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )


def test_strongest_observation_time_wins_and_preserves_all_inputs() -> None:
    timing = resolve_observation_timing(
        source_observed_at=OBSERVED_AT,
        captured_at=CAPTURED_AT,
        asserted_observed_at=ASSERTED_AT,
    )

    assert timing.resolved_observed_at == OBSERVED_AT
    assert timing.provenance == ObservationTimeProvenance.SOURCE_VERIFIED
    assert timing.captured_at == CAPTURED_AT
    assert timing.asserted_observed_at == ASSERTED_AT


def test_capture_time_is_derived_not_source_verified() -> None:
    timing = resolve_observation_timing(captured_at=CAPTURED_AT, asserted_observed_at=ASSERTED_AT)

    assert timing.resolved_observed_at == CAPTURED_AT
    assert timing.provenance == ObservationTimeProvenance.DERIVED
    assert "capture_time_used_as_derived_observation_bound" in timing.explanation_codes


def test_derived_capture_chronology_cannot_earn_supported_contribution() -> None:
    result = evaluate_attribution_evidence(
        evidence=_evidence(),
        observation_timing=resolve_observation_timing(captured_at=CAPTURED_AT),
    )

    assert result.ordering == AttributionOrdering.DERIVED_AFTER_EXECUTION
    assert result.resulting_attribution == AttributionAssessment.TEMPORAL_ASSOCIATION
    assert "derived_chronology_caps_at_temporal_association" in result.explanation_codes


def test_legacy_observed_at_is_explicitly_caller_asserted() -> None:
    result = evaluate_outcome(
        expectation=_expectation(),
        observed=_observed(source_observed_at=None, observed_at=ASSERTED_AT),
    )

    assert result.observed_at == ASSERTED_AT
    assert result.observation_timing.provenance == ObservationTimeProvenance.CALLER_ASSERTED


def test_caller_asserted_chronology_cannot_earn_supported_contribution() -> None:
    timing = resolve_observation_timing(asserted_observed_at=ASSERTED_AT)
    result = evaluate_attribution_evidence(evidence=_evidence(), observation_timing=timing)

    assert result.ordering == AttributionOrdering.UNVERIFIABLE
    assert result.resulting_attribution == AttributionAssessment.INSUFFICIENT_EVIDENCE
    assert result.causal_claim is False


def test_supported_contribution_is_earned_from_complete_non_conflicting_evidence() -> None:
    timing = resolve_observation_timing(source_observed_at=OBSERVED_AT)
    result = evaluate_attribution_evidence(evidence=_evidence(), observation_timing=timing)

    assert result.ordering == AttributionOrdering.VERIFIED_AFTER_EXECUTION
    assert result.matching_dimensions == ("qualification_score",)
    assert result.resulting_attribution == AttributionAssessment.SUPPORTED_CONTRIBUTION
    assert "non_causal_attribution_only" in result.explanation_codes
    assert result.causal_claim is False


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"execution_evidence_ids": []}, AttributionAssessment.INSUFFICIENT_EVIDENCE),
        (
            {"observed_change_dimensions": ["reply_rate"]},
            AttributionAssessment.INSUFFICIENT_EVIDENCE,
        ),
        (
            {"competing_explanations": ["pricing changed simultaneously"]},
            AttributionAssessment.TEMPORAL_ASSOCIATION,
        ),
        ({"confidence": 0.69}, AttributionAssessment.TEMPORAL_ASSOCIATION),
        (
            {"conflicting_evidence_ids": ["counterfactual_1"]},
            AttributionAssessment.CONFLICTING_EVIDENCE,
        ),
    ],
)
def test_insufficient_competing_and_conflicting_evidence_fail_closed(
    overrides: dict[str, object], expected: AttributionAssessment
) -> None:
    timing = resolve_observation_timing(source_observed_at=OBSERVED_AT)
    result = evaluate_attribution_evidence(evidence=_evidence(**overrides), observation_timing=timing)

    assert result.resulting_attribution == expected
    assert result.resulting_attribution != AttributionAssessment.SUPPORTED_CONTRIBUTION


def test_observation_before_execution_is_conflicting_not_causal() -> None:
    timing = resolve_observation_timing(source_observed_at=datetime(2026, 8, 2, 8, tzinfo=UTC))
    result = evaluate_attribution_evidence(evidence=_evidence(), observation_timing=timing)

    assert result.ordering == AttributionOrdering.CONTRADICTED
    assert result.resulting_attribution == AttributionAssessment.CONFLICTING_EVIDENCE
    assert result.causal_claim is False


def test_observation_at_execution_time_cannot_earn_supported_contribution() -> None:
    timing = resolve_observation_timing(source_observed_at=EXECUTED_AT)
    result = evaluate_attribution_evidence(evidence=_evidence(), observation_timing=timing)

    assert result.ordering == AttributionOrdering.UNVERIFIABLE
    assert result.resulting_attribution == AttributionAssessment.INSUFFICIENT_EVIDENCE
    assert "observation_not_strictly_after_execution" in result.explanation_codes
    assert result.causal_claim is False


def test_caller_supplied_supported_contribution_is_downgraded_without_evidence() -> None:
    result = evaluate_outcome(
        expectation=_expectation(),
        observed=_observed(),
        attribution=AttributionAssessment.SUPPORTED_CONTRIBUTION,
    )

    assert result.attribution == AttributionAssessment.INSUFFICIENT_EVIDENCE
    assert result.attribution_evidence is None
    assert "caller_asserted_supported_contribution_rejected" in result.explanation_codes


def test_outcome_carries_earned_attribution_for_downstream_feedback() -> None:
    result = evaluate_outcome(
        expectation=_expectation(),
        observed=_observed(),
        attribution_evidence=_evidence(),
    )

    assert result.attribution == AttributionAssessment.SUPPORTED_CONTRIBUTION
    assert result.attribution_evidence is not None
    assert result.attribution_evidence.resulting_attribution == result.attribution
    assert result.observation_timing.provenance == ObservationTimeProvenance.SOURCE_VERIFIED


def test_supported_contribution_cannot_be_forged_on_outcome_evaluation() -> None:
    with pytest.raises(ValidationError, match="requires earned attribution_evidence"):
        OutcomeEvaluation(
            outcome_evaluation_id="outcome_1",
            status=OutcomeStatus.ACHIEVED,
            attribution=AttributionAssessment.SUPPORTED_CONTRIBUTION,
            confidence=0.9,
            evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
        )


def test_attribution_artifact_chronology_must_match_outcome_chronology() -> None:
    artifact = evaluate_attribution_evidence(
        evidence=_evidence(),
        observation_timing=resolve_observation_timing(source_observed_at=OBSERVED_AT),
    )
    replayed_timing = resolve_observation_timing(
        source_observed_at=datetime(2026, 8, 4, 9, tzinfo=UTC),
    )

    with pytest.raises(ValidationError, match="observation timing must match"):
        OutcomeEvaluation(
            outcome_evaluation_id="outcome_1",
            status=OutcomeStatus.ACHIEVED,
            attribution=AttributionAssessment.SUPPORTED_CONTRIBUTION,
            attribution_evidence=artifact,
            confidence=0.9,
            observed_at=replayed_timing.resolved_observed_at,
            observation_timing=replayed_timing,
            evaluated_at=datetime(2026, 8, 5, tzinfo=UTC),
        )


def test_legacy_v1_observed_at_deserializes_as_caller_asserted_timing() -> None:
    result = OutcomeEvaluation.model_validate(
        {
            "schema_version": 1,
            "outcome_evaluation_id": "legacy_outcome_1",
            "status": "partial_progress",
            "attribution": "not_assessed",
            "confidence": 0.6,
            "observed_at": ASSERTED_AT.isoformat(),
            "evaluated_at": datetime(2026, 8, 4, tzinfo=UTC).isoformat(),
        }
    )

    assert result.observed_at == ASSERTED_AT
    assert result.observation_timing.resolved_observed_at == ASSERTED_AT
    assert result.observation_timing.provenance == ObservationTimeProvenance.CALLER_ASSERTED


def test_attribution_artifact_result_cannot_be_forged_during_deserialization() -> None:
    artifact = evaluate_attribution_evidence(
        evidence=_evidence(execution_evidence_ids=[]),
        observation_timing=resolve_observation_timing(source_observed_at=OBSERVED_AT),
    )
    payload = artifact.model_dump(mode="json")
    payload["resulting_attribution"] = "supported_contribution"

    with pytest.raises(ValidationError, match="deterministic attribution evaluation"):
        AttributionAssessmentEvidence.model_validate(payload)


def test_attribution_artifact_collections_are_immutable() -> None:
    artifact = evaluate_attribution_evidence(
        evidence=_evidence(),
        observation_timing=resolve_observation_timing(source_observed_at=OBSERVED_AT),
    )

    with pytest.raises(ValidationError):
        artifact.execution_evidence_ids += ("forged",)


def test_naive_chronology_is_rejected_before_comparison() -> None:
    with pytest.raises(ValueError, match="timezone"):
        resolve_observation_timing(source_observed_at=datetime(2026, 8, 3, 9))


def test_attribution_integrity_action_is_registered_side_effect_none_and_evidence_backed() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="analysis.assess_attribution_integrity",
            input={
                "source_observed_at": OBSERVED_AT.isoformat(),
                "evidence": _evidence().model_dump(mode="json"),
            },
        ),
        _context(),
    )

    assert result.side_effect_class.value == "none"
    assert result.output["resulting_attribution"] == "supported_contribution"
    assert result.output["causal_claim"] is False
    assert result.evidence
    assert result.limitations
