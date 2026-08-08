"""Unit tests for Commercial State / Goal / KPI Ontology Slice 2."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from backend.services.ontology import (
    COMMERCIAL_RELATIONSHIP_SPECS,
    BusinessEvent,
    BusinessObjectRef,
    BusinessObjectType,
    BusinessStateSnapshot,
    Goal,
    GoalStatus,
    Kpi,
    KpiDirection,
)
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, DecisionRecommendInput, ToolInvocation


def test_goal_minimal_shape() -> None:
    goal = Goal(
        goal_id="g1",
        name="Qualify opportunity",
        subject_refs=[{"object_type": "opportunity", "object_id": "opp-1"}],
        target_date="2026-08-31",
    )
    assert goal.status == GoalStatus.ACTIVE
    assert goal.subject_refs[0].object_type == BusinessObjectType.OPPORTUNITY


def test_goal_rejects_blank_id() -> None:
    with pytest.raises(ValidationError):
        Goal(goal_id="  ", name="x")


def test_kpi_direction_and_gap_fields() -> None:
    kpi = Kpi(
        kpi_id="k1",
        goal_id="g1",
        name="Qualification score",
        metric="qualification_score",
        direction=KpiDirection.INCREASE,
        target_value=80.0,
        current_value=62.0,
        unit="score",
    )
    assert kpi.target_value - kpi.current_value == 18.0  # type: ignore[operator]


def test_state_snapshot_is_not_evidence() -> None:
    snap = BusinessStateSnapshot(
        snapshot_id="s1",
        subject_ref=BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id="opp-1"),
        captured_at="2026-08-08T12:00:00+00:00",
        attributes={"stage": "discovery", "qualification_score": 62},
        evidence_ids=["e-crm-1"],
        confidence=0.8,
    )
    assert "claim" not in snap.model_dump()
    assert snap.evidence_ids == ["e-crm-1"]


def test_business_event_aligns_with_activity_vocabulary() -> None:
    event = BusinessEvent(
        event_id="ev1",
        event_type="stage_changed",
        subject_refs=[{"object_type": "opportunity", "object_id": "opp-1"}],
        occurred_at="2026-08-07T14:22:00+00:00",
        evidence_ids=["e-crm-stage"],
        payload={"from_stage": "discovery", "to_stage": "qualified"},
        summary="Opportunity moved to qualified",
    )
    assert event.event_type == "stage_changed"
    assert event.subject_refs[0].object_id == "opp-1"


def test_commercial_relationship_specs_present() -> None:
    names = {spec["name"] for spec in COMMERCIAL_RELATIONSHIP_SPECS}
    assert "kpi_belongs_to_goal" in names
    assert "snapshot_supported_by_evidence" in names
    assert "event_supported_by_evidence" in names


def test_decision_input_backward_compatible_without_commercial_fields() -> None:
    model = DecisionRecommendInput(
        goal="Close more deals",
        options=[{"option_id": "a", "label": "A"}],
        criteria=[{"criterion_id": "c1", "label": "C1"}],
        evidence=[{"evidence_id": "e1", "claim": "ok", "status": "known"}],
    )
    assert model.subject_refs == []
    assert model.goal_ref is None
    assert model.kpis == []
    assert model.state_snapshot is None
    assert model.recent_events == []


def test_decision_recommend_with_opportunity_goal_kpi() -> None:
    """Recommendation accepts Opportunity + Goal + KPI without changing authority."""

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
            action="decision.recommend_next_action",
            input={
                "goal": "Advance opp_123 to qualified",
                "subject_refs": [{"object_type": "opportunity", "object_id": "opp_123"}],
                "goal_ref": {
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
                        "current_value": 62,
                        "unit": "score",
                    }
                ],
                "state_snapshot": {
                    "snapshot_id": "snap-1",
                    "subject_ref": {"object_type": "opportunity", "object_id": "opp_123"},
                    "captured_at": "2026-08-08T12:00:00+00:00",
                    "attributes": {
                        "stage": "discovery",
                        "qualification_score": 62,
                        "decision_maker_identified": False,
                    },
                    "evidence_ids": ["e1"],
                },
                "recent_events": [
                    {
                        "event_id": "ev-reply",
                        "event_type": "email_sent",
                        "subject_refs": [{"object_type": "contact", "object_id": "c-jane"}],
                        "occurred_at": "2026-08-07T10:00:00+00:00",
                        "evidence_ids": ["e-gmail-1"],
                        "summary": "Jane replied positively",
                    }
                ],
                "options": [
                    {"option_id": "map_stakeholders", "label": "Map stakeholders"},
                    {"option_id": "send_pricing", "label": "Send pricing"},
                ],
                "criteria": [
                    {
                        "criterion_id": "authority_gap",
                        "label": "Close authority gap",
                        "weight": 1.0,
                    }
                ],
                "evidence": [
                    {
                        "evidence_id": "e1",
                        "claim": "Decision maker not yet identified",
                        "status": "known",
                        "confidence": 0.9,
                        "supports_option_ids": ["map_stakeholders"],
                        "supports_criterion_ids": ["authority_gap"],
                        "about_object_refs": [{"object_type": "opportunity", "object_id": "opp_123"}],
                    }
                ],
            },
        ),
        context,
    )
    assert result.action == "decision.recommend_next_action"
    assert result.side_effect_class.value == "none"
    assert result.output["recommendation"] == "map_stakeholders"
    assert "commercial_context" in result.output
    ctx = result.output["commercial_context"]
    assert ctx["goal_ref"]["goal_id"] == "g-qualify"
    assert ctx["kpis"][0]["current_value"] == 62
    assert ctx["state_snapshot"]["attributes"]["stage"] == "discovery"
    assert ctx["recent_events"][0]["event_type"] == "email_sent"
