from __future__ import annotations

from backend.domain.mission import MISSION_INTAKE_METADATA_KEY, build_mission_intake_metadata


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
