from types import SimpleNamespace
from uuid import uuid4

from backend.services.runtime_security_monitor import inspect_runtime_security


def test_security_monitor_ignores_missing_history_and_matching_scope() -> None:
    mission = uuid4()
    task = SimpleNamespace(id=uuid4(), tenant_id="tenant-a", mission_id=mission)
    lease = SimpleNamespace(id=uuid4(), tenant_id="tenant-a", task_id=task.id)
    event = SimpleNamespace(id=uuid4(), tenant_id="tenant-a", mission_id=mission)
    assert inspect_runtime_security(
        tenant_id="tenant-a", mission_id=mission, tasks=[task],
        leases=[lease], evidence=[], audits=[event],
    ) == []


def test_security_monitor_reports_observed_cross_tenant_record() -> None:
    mission = uuid4()
    task = SimpleNamespace(id=uuid4(), tenant_id="tenant-other", mission_id=mission)
    result = inspect_runtime_security(
        tenant_id="tenant-a", mission_id=mission, tasks=[task],
        leases=[], evidence=[], audits=[],
    )
    assert result == [{
        "category": "security_tenant_boundary",
        "code": f"task:{task.id}:scope_mismatch",
        "severity": "error",
    }]


def test_security_monitor_reports_orphan_lease_and_evidence() -> None:
    mission = uuid4()
    missing_task = uuid4()
    lease = SimpleNamespace(id=uuid4(), tenant_id="tenant-a", task_id=missing_task)
    evidence = SimpleNamespace(
        id=uuid4(), tenant_id="tenant-a",
        mission_id=mission, execution_task_id=missing_task,
    )
    result = inspect_runtime_security(
        tenant_id="tenant-a", mission_id=mission, tasks=[],
        leases=[lease], evidence=[evidence], audits=[],
    )
    assert {f["category"] for f in result} == {
        "security_lease_boundary", "security_evidence_boundary"
    }
