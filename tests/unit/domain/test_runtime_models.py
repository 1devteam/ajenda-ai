"""Unit tests for domain runtime models.

Tests structural properties of domain models — tenant scoping, required
fields, and column presence. Does NOT rely on SQLAlchemy column defaults
populating on Python instantiation (they only apply on DB flush).
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


def test_mission_model_accepts_required_fields() -> None:
    """Mission can be instantiated with required fields."""
    mission = Mission(
        tenant_id="tenant-a",
        objective="Build campaign",
        status=MissionState.PLANNED.value,
        metadata_json={},
    )
    assert mission.tenant_id == "tenant-a"
    assert mission.objective == "Build campaign"
    assert mission.status == MissionState.PLANNED.value


def test_runtime_models_expose_tenant_scoping() -> None:
    """All tenant-scoped domain models have a tenant_id column."""
    assert hasattr(WorkforceFleet, "tenant_id")
    assert hasattr(UserWorkforceAgent, "tenant_id")
    assert hasattr(ExecutionTask, "tenant_id")
    assert hasattr(ExecutionBranch, "tenant_id")
    assert hasattr(WorkerLease, "tenant_id")
    assert hasattr(GovernanceEvent, "tenant_id")
    assert hasattr(AuditEvent, "tenant_id")
    assert hasattr(LineageRecord, "tenant_id")


def test_lineage_record_accepts_required_fields() -> None:
    """LineageRecord can be instantiated with required fields."""
    lineage = LineageRecord(
        tenant_id="tenant-a",
        relationship_type="mission_to_task",
        metadata_json={},
    )
    assert lineage.relationship_type == "mission_to_task"
    assert lineage.metadata_json == {}


def test_execution_task_has_compliance_fields() -> None:
    """ExecutionTask exposes compliance_category and jurisdiction columns."""
    assert hasattr(ExecutionTask, "compliance_category")
    assert hasattr(ExecutionTask, "jurisdiction")
    assert hasattr(ExecutionTask, "requires_human_review")
    assert hasattr(ExecutionTask, "compliance_metadata")
