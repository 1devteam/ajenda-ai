from __future__ import annotations

from backend.domain.enums import MissionPlanStatus
from backend.domain.mission import (
    build_mission_plan_contract_metadata_from_legacy_metadata,
    build_mission_plan_contract_metadata_from_legacy_write,
    legacy_mission_plan_status_from_planning_status,
    mission_intake_allows_legacy_v1,
    mission_task_graph_allows_legacy_v1,
    stored_task_graph_requires_legacy_v1,
)


def test_legacy_write_conversion_preserves_legacy_payload_and_canonical_fields() -> None:
    metadata = build_mission_plan_contract_metadata_from_legacy_write(
        planning_status="draft",
        phases=[
            {
                "name": "Research",
                "objective": "Understand stale opportunities.",
                "stages": [
                    {
                        "name": "Collect signals",
                        "intent": "Read approved CRM fields.",
                        "desired_outputs": ["signal summary"],
                        "capability_requirements": ["crm_read"],
                        "approval_required": False,
                    }
                ],
            }
        ],
        planning_notes="Prepare recommendations only.",
        desired_outputs=[
            {
                "name": "Opportunity summary",
                "description": "Ranked recommendations with evidence.",
                "acceptance_criteria": ["Each recommendation has a rationale."],
            }
        ],
        capability_requirements=[
            {"name": "crm_read", "purpose": "Read CRM records.", "required": True, "risk_level": "low"}
        ],
        execution_strategy_hints={"decomposition": "phase_first"},
        approval_gates=[],
        operator_overrides={},
        estimated_scope={"estimated_tasks": 3, "complexity": "medium"},
        risk_annotations=[
            {
                "name": "Customer contact",
                "description": "No customer contact in this plan.",
                "risk_level": "medium",
                "mitigation": "Approval gate before outreach.",
            }
        ],
    )

    assert metadata["schema_version"] == 1
    assert metadata["objectives"] == ["Understand stale opportunities."]
    assert metadata["planned_steps"][0]["title"] == "Collect signals"
    assert metadata["legacy_v1"]["planning_status"] == "draft"
    assert metadata["legacy_v1"]["estimated_scope"]["complexity"] == "medium"


def test_legacy_metadata_backfill_conversion_handles_approved_status_mapping() -> None:
    metadata = build_mission_plan_contract_metadata_from_legacy_metadata(
        {
            "schema_version": 1,
            "planning_status": "approved",
            "phases": [
                {
                    "name": "Research",
                    "objective": "Understand stale opportunities.",
                    "stages": [],
                }
            ],
        }
    )

    assert metadata["legacy_v1"]["planning_status"] == "approved"
    assert legacy_mission_plan_status_from_planning_status("approved") == MissionPlanStatus.READY.value


def test_mission_intake_allow_legacy_v1_flag_is_explicit_opt_in() -> None:
    assert mission_intake_allows_legacy_v1({"mission_intake": {"schema_version": 1}}) is False
    assert mission_intake_allows_legacy_v1({"mission_intake": {"allow_legacy_v1": True}}) is True


def test_stored_legacy_task_graph_shape_enables_read_compatibility_without_opt_in() -> None:
    legacy_graph = {
        "schema_version": 1,
        "graph_status": "draft",
        "nodes": [{"key": "collect", "name": "Collect", "intended_task_type": "read"}],
        "edges": [],
        "metadata": {},
    }

    assert stored_task_graph_requires_legacy_v1(legacy_graph) is True
    assert mission_task_graph_allows_legacy_v1({"mission_task_graph": legacy_graph}) is True
