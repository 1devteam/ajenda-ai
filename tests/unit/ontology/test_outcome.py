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
        subject_refs=[
            BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id="opp_1")
        ],
    )


def _kpi(*, kpi_id: str, current: float, target: float, previous: float | None = None) -> Kpi:
    return Kpi(
        kpi_id=kpi_id,
        goal_id="goal_qual",
        name=kpi_id,
        metric=kpi_id,
        direction=KpiDirection.INCREASE,
        current_value=current,
        target_value=target,
        previous_value=previous,
        required=True,
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
    assert result.criteria_results[0].satisfied is True


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


def test_state_transition_code() -> None:
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
    assert "desired_state_transition_observed" in result.explanation_codes


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


def test_insufficient_evidence_without_kpi_values() -> None:
    expectation = OutcomeExpectation(
        goal=_goal(),
        baseline_kpis=[
            Kpi(
                kpi_id="qualification_score",
                goal_id="goal_qual",
                name="qs",
                metric="qualification_score",
                direction=KpiDirection.INCREASE,
                current_value=None,
                target_value=80,
            )
        ],
    )
    observed = ObservedOutcome(
        observed_kpis=[
            Kpi(
                kpi_id="qualification_score",
                goal_id="goal_qual",
                name="qs",
                metric="qualification_score",
                direction=KpiDirection.INCREASE,
                current_value=None,
                target_value=80,
            )
        ],
        missing_evidence_codes=["score_source"],
    )
    result = evaluate_outcome(expectation=expectation, observed=observed)
    assert result.status == OutcomeStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence_gaps


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
                "baseline_kpis": [
                    _kpi(kpi_id="qualification_score", current=61, target=80).model_dump(mode="json")
                ],
                "observed_kpis": [
                    _kpi(kpi_id="qualification_score", current=74, target=80).model_dump(mode="json")
                ],
            },
        ),
        context,
    )
    assert result.action == "analysis.evaluate_outcome"
    assert result.output["status"] == "partial_progress"
    assert result.evidence
