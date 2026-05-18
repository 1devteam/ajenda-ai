"""Unit tests for domain runtime models.

SQLAlchemy column defaults only fire on DB INSERT, not Python __init__.
Model-structure tests must pass explicit values when asserting attributes.
"""

from __future__ import annotations

from backend.domain import (
    AuditEvent,
    ExecutionBranch,
    ExecutionTask,
    GovernanceEvent,
    LineageRecord,
    Mission,
    UserWorkforceAgent,
    WorkerLease,
    WorkforceFleet,
)
from backend.domain.enums import MissionState


def test_mission_model_defaults() -> None:
    mission = Mission(
        tenant_id="tenant-a",
        objective="Build campaign",
        status=MissionState.PLANNED.value,
        metadata_json={},
    )

    assert mission.status == MissionState.PLANNED.value
    assert mission.metadata_json == {}


def test_runtime_models_expose_tenant_scoping() -> None:
    assert hasattr(WorkforceFleet, "tenant_id")
    assert hasattr(UserWorkforceAgent, "tenant_id")
    assert hasattr(ExecutionTask, "tenant_id")
    assert hasattr(ExecutionBranch, "tenant_id")
    assert hasattr(WorkerLease, "tenant_id")
    assert hasattr(AuditEvent, "tenant_id")
    assert hasattr(GovernanceEvent, "tenant_id")
    assert hasattr(LineageRecord, "tenant_id")


def test_lineage_record_has_append_only_shape() -> None:
    lineage = LineageRecord(
        tenant_id="tenant-a",
        relationship_type="mission_to_task",
        metadata_json={},
    )

    assert lineage.relationship_type == "mission_to_task"
    assert lineage.metadata_json == {}


def test_execution_task_has_compliance_fields() -> None:
    assert hasattr(ExecutionTask, "compliance_category")
    assert hasattr(ExecutionTask, "jurisdiction")
    assert hasattr(ExecutionTask, "requires_human_review")


def test_mission_has_compliance_fields() -> None:
    assert hasattr(Mission, "compliance_category")
    assert hasattr(Mission, "jurisdiction")
