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


def test_security_monitor_flags_unleased_versioned_running_task() -> None:
    mission = uuid4()
    task = SimpleNamespace(
        id=uuid4(), tenant_id="tenant-a", mission_id=mission,
        status="running", metadata_json={"runtime_evidence_contract_version": "1"},
    )
    result = inspect_runtime_security(
        tenant_id="tenant-a", mission_id=mission, tasks=[task],
        leases=[], evidence=[], audits=[],
    )
    assert any(f["category"] == "security_lease_integrity" for f in result)


def test_security_monitor_flags_observation_claiming_runtime_authority() -> None:
    mission = uuid4()
    event = SimpleNamespace(
        id=uuid4(), tenant_id="tenant-a", mission_id=mission,
        category="mission_information", payload_json={"grants_execution_authority": True},
    )
    result = inspect_runtime_security(
        tenant_id="tenant-a", mission_id=mission, tasks=[], leases=[],
        evidence=[], audits=[event],
    )
    assert result[0]["category"] == "security_observation_integrity"


def test_versioned_task_requires_durable_start_event() -> None:
    mission = uuid4()
    task = SimpleNamespace(
        id=uuid4(), tenant_id="tenant-a", mission_id=mission,
        status="running", metadata_json={"runtime_evidence_contract_version": "1"},
    )
    lease = SimpleNamespace(id=uuid4(), tenant_id="tenant-a", task_id=task.id)
    missing = inspect_runtime_security(
        tenant_id="tenant-a", mission_id=mission, tasks=[task],
        leases=[lease], evidence=[], audits=[],
    )
    assert any(f["category"] == "security_trace_integrity" for f in missing)

    event = SimpleNamespace(
        id=uuid4(), tenant_id="tenant-a", mission_id=mission,
        category="mission_information", action="execution_started",
        payload_json={
            "schema_version": 1, "task_id": str(task.id),
            "lease_id": str(lease.id),
            "grants_execution_authority": False,
        },
    )
    observed = inspect_runtime_security(
        tenant_id="tenant-a", mission_id=mission, tasks=[task],
        leases=[lease], evidence=[], audits=[event],
    )
    assert observed == []


def test_security_monitor_rejects_start_event_bound_to_wrong_lease() -> None:
    mission = uuid4()
    task = SimpleNamespace(
        id=uuid4(), tenant_id="tenant-a", mission_id=mission,
        status="running", metadata_json={"runtime_evidence_contract_version": "1"},
    )
    lease = SimpleNamespace(id=uuid4(), tenant_id="tenant-a", task_id=task.id)
    forged = SimpleNamespace(
        id=uuid4(), tenant_id="tenant-a", mission_id=mission,
        category="mission_information", action="execution_started",
        payload_json={
            "schema_version": 1, "task_id": str(task.id),
            "lease_id": str(uuid4()), "grants_execution_authority": False,
        },
    )
    findings = inspect_runtime_security(
        tenant_id="tenant-a", mission_id=mission,
        tasks=[task], leases=[lease], evidence=[], audits=[forged],
    )
    assert any(f["category"] == "security_trace_integrity" for f in findings)
