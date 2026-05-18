from __future__ import annotations

from backend.domain.enums import ComplianceCategory, ComplianceJurisdiction
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission


def test_compliance_enums_expose_stable_values() -> None:
    assert ComplianceCategory.OPERATIONAL.value == "operational"
    assert ComplianceCategory.EMPLOYMENT.value == "employment"
    assert ComplianceJurisdiction.GLOBAL.value == "global"
    assert ComplianceJurisdiction.COLORADO.value == "colorado"


def test_mission_compliance_defaults_are_model_level_truth() -> None:
    mission = Mission(tenant_id="tenant-a", objective="x")

    assert mission.compliance_category is None


def test_execution_task_compliance_defaults_are_model_level_truth() -> None:
    task = ExecutionTask(
        tenant_id="tenant-a",
        mission_id=None,
        title="x",
        description="y",
    )  # type: ignore[arg-type]

    assert task.compliance_category is None
    assert task.requires_human_review is None
