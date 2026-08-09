"""Unit tests for Outcome Intelligence Slice 1."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from backend.services.ontology.commercial_state import (
    BusinessStateSnapshot,
    Goal,
    Kpi,
    KpiDirection,
)
from backend.services.ontology.evaluation import GoalProgressStatus
from backend.services.ontology.outcome import (
    AttributionAssessment,
    DirectionAssessment,
    ObservedOutcome,
    OutcomeExpectation,
    OutcomeStatus,
    evaluate_outcome,
)
from backend.services.ontology.types import BusinessObjectRef, BusinessObjectType
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _goal() -> Goal:
    return Goal(
        goal_id="goal_qual",
        name="Qualify opportunity",
        subject_refs=[BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id="opp_1")],
    )


def _kpi(
    *,
    kpi_id: str,
    current: float | None,
    target: float | None,
    previous: float | None = None,
    required: bool = True,
    metric: str | None = None,
    direction: KpiDirection = KpiDirection.INCREASE,
    goal_id: str = "goal_qual",
) -> Kpi:
    return Kpi(
        kpi_id=kpi_id,
        goal_id=goal_id,
        name=kpi_id,
        metric=metric or kpi_id,
        direction=direction,
        current_value=current,
        target_value=target,
        previous_value=previous,
        required=required,
    )


def _snap(*, sid: str, attrs: dict) -> BusinessStateSnapshot:
    return BusinessStateSnapshot(
        snapshot_id=sid,
        subject_ref=BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id="opp_1"),
        captured_at=datetime(2026, 8, 1, tzinfo=UTC),
        attributes=attrs,
        evidence_ids=["ev_1"],
    )


def test_kpi_delta_partial_progress_toward_target() -> None:
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[_kpi(kpi_id="qualification_score", current=61, target=80)],
    )
    observed = ObservedOutcome(
        observed_kpis=[_kpi(kpi_id="qualification_score", current=74, target=80)],
        evidence_ids=["ev_2"],
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.status == OutcomeStatus.PARTIAL_PROGRESS
    assert len(result.kpi_deltas) == 1
    delta = result.kpi_deltas[0]
    assert delta.before == 61
    assert delta.after == 74
    assert delta.target == 80
    assert delta.absolute_change == 13
    assert delta.previous_gap == 19
    assert delta.remaining_gap == 6
    assert delta.gap_closed == 13
    assert abs((delta.gap_closure_ratio or 0) - (13 / 19)) < 1e-6
    assert delta.target_reached is False
    assert delta.direction_assessment == DirectionAssessment.TOWARD_TARGET
    assert "gap_reduced" in delta.explanation_codes
    assert result.attribution == AttributionAssessment.NOT_ASSESSED


def test_achieved_when_all_targets_reached() -> None:
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[_kpi(kpi_id="qualification_score", current=61, target=80)],
        success_criteria_codes=["score_at_target"],
    )
    observed = ObservedOutcome(
        observed_kpis=[_kpi(kpi_id="qualification_score", current=80, target=80)],
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.status == OutcomeStatus.ACHIEVED
    assert result.kpi_deltas[0].direction_assessment == DirectionAssessment.TARGET_REACHED
    assert result.criteria_results[0].satisfied is None
    assert result.criteria_results[0].explanation_code == "criteria_not_independently_evaluated_v1"


def test_regressed_when_moved_away() -> None:
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[_kpi(kpi_id="qualification_score", current=70, target=80)],
    )
    observed = ObservedOutcome(
        observed_kpis=[_kpi(kpi_id="qualification_score", current=55, target=80)],
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.status == OutcomeStatus.REGRESSED
    assert result.kpi_deltas[0].direction_assessment == DirectionAssessment.AWAY_FROM_TARGET


def test_no_material_change() -> None:
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[_kpi(kpi_id="qualification_score", current=61, target=80)],
    )
    observed = ObservedOutcome(
        observed_kpis=[_kpi(kpi_id="qualification_score", current=61, target=80)],
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.status == OutcomeStatus.NO_MATERIAL_CHANGE


def test_state_transition_code_neutral() -> None:
    """Any attribute change is observed — never labeled 'desired' without a contract."""
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[_kpi(kpi_id="qualification_score", current=61, target=80)],
        baseline_snapshot=_snap(sid="s0", attrs={"decision_maker_identified": False}),
    )
    observed = ObservedOutcome(
        observed_kpis=[_kpi(kpi_id="qualification_score", current=74, target=80)],
        observed_snapshot=_snap(sid="s1", attrs={"decision_maker_identified": True}),
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.state_changes is not None
    assert any(c.key == "decision_maker_identified" for c in result.state_changes.changes)
    assert "state_transition_observed" in result.explanation_codes
    assert "desired_state_transition_observed" not in result.explanation_codes


def test_negative_state_transition_still_neutral() -> None:
    """Regression in state still gets the neutral observation code, not 'desired'."""
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[_kpi(kpi_id="qualification_score", current=74, target=80)],
        baseline_snapshot=_snap(sid="s0", attrs={"decision_maker_identified": True}),
    )
    observed = ObservedOutcome(
        observed_kpis=[_kpi(kpi_id="qualification_score", current=61, target=80)],
        observed_snapshot=_snap(sid="s1", attrs={"decision_maker_identified": False}),
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.state_changes is not None
    assert any(
        c.key == "decision_maker_identified" and c.change_type == "changed" for c in result.state_changes.changes
    )
    assert "state_transition_observed" in result.explanation_codes
    assert "desired_state_transition_observed" not in result.explanation_codes
    assert result.status == OutcomeStatus.REGRESSED


def test_attribution_never_invented() -> None:
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[_kpi(kpi_id="qualification_score", current=61, target=80)],
    )
    observed = ObservedOutcome(
        observed_kpis=[_kpi(kpi_id="qualification_score", current=74, target=80)],
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.attribution == AttributionAssessment.NOT_ASSESSED

    result2 = evaluate_outcome(
        expectation=expectation,
        observed=observed,
        attribution=AttributionAssessment.TEMPORAL_ASSOCIATION,
    )
    assert result2.attribution == AttributionAssessment.TEMPORAL_ASSOCIATION
    assert "attribution_temporal_association" in result2.explanation_codes


def test_explicit_observation_time_is_preserved_separately_from_evaluation_time() -> None:
    observed_at = datetime(2026, 8, 3, tzinfo=UTC)
    evaluated_at = datetime(2026, 8, 4, tzinfo=UTC)
    result = evaluate_outcome(
        expectation=OutcomeExpectation(
            goal=_goal(),
            baseline_kpis=[_kpi(kpi_id="qualification_score", current=61, target=80)],
        ),
        observed=ObservedOutcome(
            observed_kpis=[_kpi(kpi_id="qualification_score", current=74, target=80)],
            observed_at=observed_at,
        ),
        evaluated_at=evaluated_at,
    )

    assert result.observed_at == observed_at
    assert result.evaluated_at == evaluated_at


def test_outcome_observation_time_remains_unknown_when_not_supplied() -> None:
    result = evaluate_outcome(
        expectation=OutcomeExpectation(
            goal=_goal(),
            baseline_kpis=[_kpi(kpi_id="qualification_score", current=61, target=80)],
        ),
        observed=ObservedOutcome(
            observed_kpis=[_kpi(kpi_id="qualification_score", current=74, target=80)],
            events=[
                {
                    "event_id": "event_1",
                    "event_type": "stage_changed",
                    "occurred_at": "2026-08-03T00:00:00+00:00",
                }
            ],
        ),
    )

    # A recorded event has its own actual occurred_at, but it is not automatically
    # proof of when the aggregate KPI outcome was observed.
    assert result.observed_at is None


def test_insufficient_evidence_without_kpi_values() -> None:
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[_kpi(kpi_id="qualification_score", current=None, target=80)],
    )
    observed = ObservedOutcome(
        observed_kpis=[_kpi(kpi_id="qualification_score", current=None, target=80)],
        missing_evidence_codes=["score_source"],
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.status == OutcomeStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence_gaps


def test_required_kpi_unknown_blocks_achieved() -> None:
    """Required KPI with missing values must prevent ACHIEVED even if another KPI hits target."""
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[
            _kpi(kpi_id="qualification_score", current=61, target=80, required=True),
            _kpi(kpi_id="reply_rate", current=0.1, target=0.4, required=True),
        ],
    )
    observed = ObservedOutcome(
        observed_kpis=[
            _kpi(kpi_id="qualification_score", current=80, target=80, required=True),
            _kpi(kpi_id="reply_rate", current=None, target=0.4, required=True),
        ],
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.status != OutcomeStatus.ACHIEVED
    assert result.status in {OutcomeStatus.INSUFFICIENT_EVIDENCE, OutcomeStatus.INCONCLUSIVE}
    assert "required_kpi_insufficient_data" in result.explanation_codes


def test_required_baseline_kpi_omitted_from_observed_blocks_achieved() -> None:
    """An omitted required observation must remain visible and prevent ACHIEVED."""
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[
            _kpi(kpi_id="qualification_score", current=61, target=80, required=True),
            _kpi(kpi_id="reply_rate", current=0.1, target=0.4, required=True),
        ],
    )
    observed = ObservedOutcome(
        observed_kpis=[
            _kpi(kpi_id="qualification_score", current=80, target=80, required=True),
        ],
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.status != OutcomeStatus.ACHIEVED
    assert "required_kpi_insufficient_data" in result.explanation_codes
    missing_delta = next(delta for delta in result.kpi_deltas if delta.kpi_id == "reply_rate")
    assert missing_delta.required is True
    assert missing_delta.direction_assessment == DirectionAssessment.INSUFFICIENT_DATA
    assert missing_delta.explanation_codes == ["observed_kpi_missing"]
    assert result.observed_evaluation is not None
    assert result.observed_evaluation.status == GoalProgressStatus.INSUFFICIENT_DATA
    missing_evaluation = next(
        evaluation for evaluation in result.observed_evaluation.kpi_evaluations if evaluation.kpi_id == "reply_rate"
    )
    assert missing_evaluation.status == "insufficient_data"


def test_foreign_required_baseline_kpi_omitted_from_observed_blocks_nested_achieved() -> None:
    """A foreign goal ID must not hide an omitted required KPI from the nested result."""
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[
            _kpi(kpi_id="qualification_score", current=61, target=80, required=True),
            _kpi(
                kpi_id="reply_rate",
                current=0.1,
                target=0.4,
                required=True,
                goal_id="goal_foreign",
            ),
        ],
    )
    observed = ObservedOutcome(
        observed_kpis=[
            _kpi(kpi_id="qualification_score", current=80, target=80, required=True),
        ],
    )

    result = evaluate_outcome(expectation=expectation, observed=observed)

    assert result.status != OutcomeStatus.ACHIEVED
    assert "required_kpi_insufficient_data" in result.explanation_codes
    assert result.observed_evaluation is not None
    assert result.observed_evaluation.status == GoalProgressStatus.INSUFFICIENT_DATA
    missing_evaluation = next(
        evaluation for evaluation in result.observed_evaluation.kpi_evaluations if evaluation.kpi_id == "reply_rate"
    )
    assert missing_evaluation.status == "insufficient_data"


def test_achieved_blocked_by_required_evidence_gap() -> None:
    """All KPIs at target + declared evidence gaps → not ACHIEVED."""
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[_kpi(kpi_id="qualification_score", current=61, target=80)],
    )
    observed = ObservedOutcome(
        observed_kpis=[_kpi(kpi_id="qualification_score", current=80, target=80)],
        missing_evidence_codes=["source_of_score"],
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.status == OutcomeStatus.INSUFFICIENT_EVIDENCE
    assert "required_evidence_missing" in result.explanation_codes
    assert "all_targets_reached" in result.explanation_codes
    assert result.evidence_gaps


def test_success_criteria_not_independently_evaluated() -> None:
    """Opaque criteria codes are recorded; satisfaction is never invented from aggregate status."""
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[_kpi(kpi_id="qualification_score", current=61, target=80)],
        success_criteria_codes=["unrelated_code_a", "unrelated_code_b"],
    )
    observed = ObservedOutcome(
        observed_kpis=[_kpi(kpi_id="qualification_score", current=80, target=80)],
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.status == OutcomeStatus.ACHIEVED
    assert len(result.criteria_results) == 2
    for cr in result.criteria_results:
        assert cr.satisfied is None
        assert cr.explanation_code == "criteria_not_independently_evaluated_v1"
    assert "criteria_recorded_not_evaluated" in result.explanation_codes


def test_kpi_definition_mismatch() -> None:
    """Same kpi_id but different metric/direction/goal_id is a contract mismatch, not a delta."""
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[
            _kpi(kpi_id="score", current=61, target=80, metric="qualification_score"),
        ],
    )
    observed = ObservedOutcome(
        observed_kpis=[
            _kpi(kpi_id="score", current=80, target=80, metric="engagement_score"),
        ],
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.kpi_deltas[0].direction_assessment == DirectionAssessment.INSUFFICIENT_DATA
    assert "kpi_definition_mismatch" in result.kpi_deltas[0].explanation_codes
    assert result.status != OutcomeStatus.ACHIEVED


def test_action_registry_evaluate_outcome() -> None:
    registry = get_default_action_registry(rebuild=True)
    definition = registry.get("analysis.evaluate_outcome")
    assert definition.side_effect_class.value == "none"
    context = ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )
    result = registry.invoke(
        ToolInvocation(
            action="analysis.evaluate_outcome",
            input={
                "goal": _goal().model_dump(mode="json"),
                "baseline_kpis": [_kpi(kpi_id="qualification_score", current=61, target=80).model_dump(mode="json")],
                "observed_kpis": [_kpi(kpi_id="qualification_score", current=74, target=80).model_dump(mode="json")],
            },
        ),
        context,
    )
    assert result.action == "analysis.evaluate_outcome"
    assert result.output["status"] == "partial_progress"
    assert result.evidence
