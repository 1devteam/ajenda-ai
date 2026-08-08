"""Unit tests for Evaluation Intelligence Slice 1."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from backend.services.ontology import (
    BusinessObjectType,
    Goal,
    GoalProgressStatus,
    Kpi,
    KpiDirection,
    OntologyRelationshipSpec,
    compare_state_snapshots,
    evaluate_goal_progress,
    evaluate_kpi,
)
from backend.services.ontology.commercial_state import COMMERCIAL_RELATIONSHIP_SPECS, BusinessStateSnapshot
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def test_evaluate_kpi_increase_gap() -> None:
    kpi = Kpi(
        kpi_id="k1",
        goal_id="g1",
        name="Score",
        metric="qualification_score",
        direction=KpiDirection.INCREASE,
        current_value=61,
        target_value=80,
        previous_value=43,
    )
    ev = evaluate_kpi(kpi)
    assert ev.gap == 19
    assert ev.change == 18
    assert ev.target_reached is False
    assert abs((ev.attainment or 0) - 61 / 80) < 1e-6
    assert ev.status == "gap"


def test_evaluate_kpi_achieved() -> None:
    kpi = Kpi(
        kpi_id="k1",
        goal_id="g1",
        name="Score",
        metric="qualification_score",
        current_value=80,
        target_value=80,
    )
    ev = evaluate_kpi(kpi)
    assert ev.target_reached is True
    assert ev.status == "ok"


def test_state_comparison_added_changed_removed() -> None:
    earlier = BusinessStateSnapshot(
        snapshot_id="s0",
        subject_ref={"object_type": "opportunity", "object_id": "opp1"},
        captured_at="2026-08-01T00:00:00+00:00",
        attributes={"stage": "discovery", "old": 1},
    )
    later = BusinessStateSnapshot(
        snapshot_id="s1",
        subject_ref={"object_type": "opportunity", "object_id": "opp1"},
        captured_at="2026-08-08T00:00:00+00:00",
        attributes={"stage": "qualified", "new": 2},
    )
    cmp = compare_state_snapshots(earlier, later)
    types = {c.key: c.change_type for c in cmp.changes}
    assert types["stage"] == "changed"
    assert types["old"] == "removed"
    assert types["new"] == "added"


def test_goal_progress_at_risk_with_gap() -> None:
    goal = Goal(goal_id="g1", name="Qualify", target_date=date(2026, 8, 31))
    kpi = Kpi(
        kpi_id="k1",
        goal_id="g1",
        name="Score",
        metric="qualification_score",
        current_value=61,
        target_value=80,
        previous_value=43,
    )
    result = evaluate_goal_progress(goal=goal, kpis=[kpi])
    assert result.status == GoalProgressStatus.AT_RISK
    assert any(g.code.startswith("kpi_gap") for g in result.progress_gaps)
    assert result.kpi_evaluations[0].gap == 19


def test_goal_progress_insufficient_without_kpi() -> None:
    goal = Goal(goal_id="g1", name="Qualify")
    result = evaluate_goal_progress(goal=goal, kpis=[])
    assert result.status == GoalProgressStatus.INSUFFICIENT_DATA


def test_commercial_relationship_specs_typed() -> None:
    assert all(isinstance(s, OntologyRelationshipSpec) for s in COMMERCIAL_RELATIONSHIP_SPECS)
    names = {s.name for s in COMMERCIAL_RELATIONSHIP_SPECS}
    assert "kpi_belongs_to_goal" in names


def test_analysis_evaluate_goal_progress_action() -> None:
    registry = get_default_action_registry(rebuild=True)
    context = ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )
    result = registry.invoke(
        ToolInvocation(
            action="analysis.evaluate_goal_progress",
            input={
                "goal": {
                    "goal_id": "g-qualify",
                    "name": "Qualify opportunity",
                    "subject_refs": [{"object_type": "opportunity", "object_id": "opp_123"}],
                    "target_date": "2026-08-31",
                },
                "kpis": [
                    {
                        "kpi_id": "k-score",
                        "goal_id": "g-qualify",
                        "name": "Qualification score",
                        "metric": "qualification_score",
                        "direction": "increase",
                        "target_value": 80,
                        "current_value": 61,
                        "previous_value": 43,
                    }
                ],
                "current_state": {
                    "snapshot_id": "snap-1",
                    "subject_ref": {"object_type": "opportunity", "object_id": "opp_123"},
                    "captured_at": "2026-08-08T12:00:00+00:00",
                    "attributes": {"stage": "discovery", "qualification_score": 61},
                    "evidence_ids": ["e1"],
                },
                "previous_state": {
                    "snapshot_id": "snap-0",
                    "subject_ref": {"object_type": "opportunity", "object_id": "opp_123"},
                    "captured_at": "2026-08-01T12:00:00+00:00",
                    "attributes": {"stage": "discovery", "qualification_score": 43},
                },
                "evidence_ids": ["e1"],
            },
        ),
        context,
    )
    assert result.action == "analysis.evaluate_goal_progress"
    assert result.side_effect_class.value == "none"
    assert result.output["status"] == "at_risk"
    assert result.output["kpi_evaluations"][0]["gap"] == 19
    assert result.output["state_changes"]["changes"]


def test_typed_temporal_fields() -> None:
    goal = Goal(goal_id="g", name="n", target_date="2026-08-31")
    assert goal.target_date == date(2026, 8, 31)
    snap = BusinessStateSnapshot(
        snapshot_id="s",
        subject_ref={"object_type": BusinessObjectType.OPPORTUNITY, "object_id": "o"},
        captured_at="2026-08-08T12:00:00Z",
    )
    assert isinstance(snap.captured_at, datetime)
    assert snap.captured_at.tzinfo is not None or snap.captured_at == datetime(2026, 8, 8, 12, 0)
