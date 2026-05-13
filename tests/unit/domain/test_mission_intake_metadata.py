from __future__ import annotations

import json

from backend.domain.mission import (
    MISSION_INTAKE_METADATA_KEY,
    MISSION_PLAN_METADATA_KEY,
    MISSION_TASK_GRAPH_METADATA_KEY,
    build_mission_intake_metadata,
    build_mission_plan_metadata,
    build_mission_task_graph_metadata,
)


def test_build_mission_intake_metadata_preserves_first_class_intake_fields() -> None:
    metadata = build_mission_intake_metadata(
        success_criteria=[{"description": "Outcome has evidence.", "evidence": ["audit summary"]}],
        constraints=[{"name": "No outbound contact", "description": "Prepare only.", "hard": True}],
        operator_notes="Enterprise accounts first.",
        context={"source": "crm"},
        priority="urgent",
        approval_required=True,
        approval_expectations=["operator approval before outreach"],
        budget_limits={"max_tasks": 3},
        scope_limits=["last 30 days"],
        allowed_actions=["read_crm"],
        allowed_tools=["crm"],
    )

    intake = metadata[MISSION_INTAKE_METADATA_KEY]
    assert intake == {
        "schema_version": 1,
        "success_criteria": [{"description": "Outcome has evidence.", "evidence": ["audit summary"]}],
        "constraints": [{"name": "No outbound contact", "description": "Prepare only.", "hard": True}],
        "operator_notes": "Enterprise accounts first.",
        "context": {"source": "crm"},
        "priority": "urgent",
        "approval_required": True,
        "approval_expectations": ["operator approval before outreach"],
        "budget_limits": {"max_tasks": 3},
        "scope_limits": ["last 30 days"],
        "allowed_actions": ["read_crm"],
        "allowed_tools": ["crm"],
    }


def test_build_mission_plan_metadata_preserves_first_class_planning_fields() -> None:
    metadata = build_mission_plan_metadata(
        planning_status="draft",
        phases=[
            {
                "name": "Research",
                "objective": "Understand the opportunity set.",
                "stages": [
                    {
                        "name": "Collect signals",
                        "intent": "Gather tenant-approved CRM and analytics signals.",
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
        approval_gates=[
            {
                "name": "Operator review",
                "description": "Review recommendations before outreach.",
                "required_before": "customer_contact",
                "status": "required",
            }
        ],
        operator_overrides={"max_parallelism": 1},
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

    plan = metadata[MISSION_PLAN_METADATA_KEY]
    assert plan == {
        "schema_version": 1,
        "planning_status": "draft",
        "phases": [
            {
                "name": "Research",
                "objective": "Understand the opportunity set.",
                "stages": [
                    {
                        "name": "Collect signals",
                        "intent": "Gather tenant-approved CRM and analytics signals.",
                        "desired_outputs": ["signal summary"],
                        "capability_requirements": ["crm_read"],
                        "approval_required": False,
                    }
                ],
            }
        ],
        "planning_notes": "Prepare recommendations only.",
        "desired_outputs": [
            {
                "name": "Opportunity summary",
                "description": "Ranked recommendations with evidence.",
                "acceptance_criteria": ["Each recommendation has a rationale."],
            }
        ],
        "capability_requirements": [
            {"name": "crm_read", "purpose": "Read CRM records.", "required": True, "risk_level": "low"}
        ],
        "execution_strategy_hints": {"decomposition": "phase_first"},
        "approval_gates": [
            {
                "name": "Operator review",
                "description": "Review recommendations before outreach.",
                "required_before": "customer_contact",
                "status": "required",
            }
        ],
        "operator_overrides": {"max_parallelism": 1},
        "estimated_scope": {"estimated_tasks": 3, "complexity": "medium"},
        "risk_annotations": [
            {
                "name": "Customer contact",
                "description": "No customer contact in this plan.",
                "risk_level": "medium",
                "mitigation": "Approval gate before outreach.",
            }
        ],
    }


def test_build_mission_task_graph_metadata_preserves_first_class_graph_fields() -> None:
    metadata = build_mission_task_graph_metadata(
        mission_id="mission-123",
        graph_status="draft",
        nodes=[
            {
                "key": "collect-signals",
                "name": "Collect signals",
                "intended_task_type": "crm_research",
                "capability_references": [{"name": "crm_read", "purpose": "Read CRM records."}],
                "input_contract": {"source": "crm"},
                "expected_output_contract": {"artifact": "signal_summary"},
                "risk_level": "low",
                "approval_required": False,
                "execution_constraints": {"read_only": True},
                "operator_notes": "Tenant-approved fields only.",
            }
        ],
        edges=[],
        operator_notes="Contract only.",
        validation_metadata={"validation_status": "valid", "node_count": 1, "edge_count": 0},
    )

    task_graph = metadata[MISSION_TASK_GRAPH_METADATA_KEY]
    assert task_graph == {
        "schema_version": 1,
        "mission_id": "mission-123",
        "graph_status": "draft",
        "graph_version": 1,
        "graph_fingerprint": None,
        "nodes": [
            {
                "key": "collect-signals",
                "name": "Collect signals",
                "intended_task_type": "crm_research",
                "capability_references": [{"name": "crm_read", "purpose": "Read CRM records."}],
                "input_contract": {"source": "crm"},
                "expected_output_contract": {"artifact": "signal_summary"},
                "risk_level": "low",
                "approval_required": False,
                "execution_constraints": {"read_only": True},
                "operator_notes": "Tenant-approved fields only.",
            }
        ],
        "edges": [],
        "operator_notes": "Contract only.",
        "validation_metadata": {"validation_status": "valid", "node_count": 1, "edge_count": 0},
    }


def test_build_mission_plan_contract_metadata_defaults_are_deterministic_and_json_safe() -> None:
    from backend.domain.mission import build_mission_plan_contract_metadata

    metadata = build_mission_plan_contract_metadata()

    assert metadata == {
        "schema_version": 1,
        "objectives": [],
        "constraints": [],
        "assumptions": [],
        "acceptance_criteria": [],
        "planned_steps": [],
        "risk_notes": [],
    }
    assert json.loads(json.dumps(metadata)) == metadata


def test_mission_plan_status_values_are_explicit() -> None:
    from backend.domain.enums import MissionPlanStatus

    assert [status.value for status in MissionPlanStatus] == ["draft", "ready", "superseded", "cancelled"]


def test_mission_plan_contract_metadata_preserves_json_safe_planned_steps() -> None:
    from backend.domain.mission import build_mission_plan_contract_metadata

    metadata = build_mission_plan_contract_metadata(
        objectives=["Recover stale opportunities."],
        constraints=["No customer contact."],
        assumptions=["CRM data is current."],
        acceptance_criteria=["Recommendations include rationale."],
        planned_steps=[
            {
                "sequence": 1,
                "title": "Collect signals",
                "description": "Read approved CRM fields.",
                "depends_on": [],
                "expected_output": "Signal summary",
                "metadata": {"source": "crm"},
            }
        ],
        risk_notes=["Outbound communication requires later approval."],
    )

    assert metadata["planned_steps"][0]["sequence"] == 1
    assert json.loads(json.dumps(metadata)) == metadata
