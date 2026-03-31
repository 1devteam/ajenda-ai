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
    mission = Mission(tenant_id="tenant-a", objective="Build campaign")
    assert mission.status == MissionState.PLANNED.value
    assert mission.metadata_json == {}


def test_runtime_models_expose_tenant_scoping() -> None:
    assert hasattr(WorkforceFleet, "tenant_id")
    assert hasattr(UserWorkforceAgent, "tenant_id")
    assert hasattr(ExecutionTask, "tenant_id")
    assert hasattr(ExecutionBranch, "tenant_id")
    assert hasattr(WorkerLease, "tenant_id")
    assert hasattr(GovernanceEvent, "tenant_id")
    assert hasattr(AuditEvent, "tenant_id")
    assert hasattr(LineageRecord, "tenant_id")


def test_lineage_record_has_append_only_shape() -> None:
    lineage = LineageRecord(tenant_id="tenant-a", relationship_type="mission_to_task")
    assert lineage.relationship_type == "mission_to_task"
    assert lineage.metadata_json == {}
