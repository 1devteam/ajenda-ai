from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.services.continuous_assurance import ContinuousAssuranceService


def test_status_precedence_prefers_contradiction_over_drift_and_incomplete() -> None:
    status = ContinuousAssuranceService._status(
        runtime_contradictions=True,
        missing_evidence=True,
        reconciliation_status="drifted",
        lifecycle_state="contradictory",
    )
    assert status == "contradictory"


def test_status_is_aligned_when_runtime_and_reconciliation_are_clean() -> None:
    status = ContinuousAssuranceService._status(
        runtime_contradictions=False,
        missing_evidence=False,
        reconciliation_status="aligned",
        lifecycle_state="current",
    )
    assert status == "aligned"


def test_reconcile_mission_persists_assurance_only_without_mutating_mission(monkeypatch) -> None:
    mission_id = uuid.uuid4()
    mission = SimpleNamespace(
        id=mission_id,
        tenant_id="tenant-a",
        status="completed",
        metadata_json={"sentinel": "unchanged"},
    )
    session = MagicMock()
    session.scalars.side_effect = [[], [], [], [], []]

    runtime = SimpleNamespace(
        contradictions=[],
        missing_evidence=[],
        first_divergence=None,
        mission_status="completed",
        nodes=[],
        edges=[],
        task_flows=[],
        record_flows=[],
    )
    reconciliation = SimpleNamespace(
        status="aligned",
        semantic_status="aligned",
        semantic_mismatch_codes=(),
        semantic_drift_codes=(),
    )
    runtime_state = SimpleNamespace(
        lifecycle_state="current",
        epistemic_confidence=0.8,
        contradiction_codes=(),
        runtime_reconciliation=reconciliation,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.mission_runtime_evidence_projection.build_mission_runtime_evidence_projection",
        lambda **_: runtime,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.deliverable_runtime_observability.build_deliverable_runtime_state_read",
        lambda _: runtime_state,
    )

    service = ContinuousAssuranceService(session)
    service._snapshots = MagicMock()
    service._snapshots.latest_for_mission.return_value = None
    service._snapshots.append.side_effect = lambda snapshot: snapshot

    snapshot = service.reconcile_mission(tenant_id="tenant-a", mission=mission)

    assert snapshot.status == "aligned"
    assert snapshot.finding_count == 0
    assert snapshot.calibration_eligible is True
    assert snapshot.calibration_outcome_aligned is True
    assert snapshot.authority_class == "read_model"
    assert snapshot.grants_execution_authority is False
    assert mission.status == "completed"
    assert mission.metadata_json == {"sentinel": "unchanged"}
    session.add.assert_not_called()


def test_reconcile_mission_records_first_divergence_and_semantic_drift(monkeypatch) -> None:
    mission = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id="tenant-a",
        status="completed",
        metadata_json={},
    )
    session = MagicMock()
    session.scalars.side_effect = [[], [], [], [], []]
    runtime = SimpleNamespace(
        contradictions=[],
        missing_evidence=[],
        first_divergence="task:abc:missing_evidence",
        mission_status="completed",
        nodes=[],
        edges=[],
        task_flows=[],
        record_flows=[],
    )
    reconciliation = SimpleNamespace(
        status="drifted",
        semantic_status="drifted",
        semantic_mismatch_codes=(),
        semantic_drift_codes=("goal_semantics_not_observed",),
    )
    runtime_state = SimpleNamespace(
        lifecycle_state="current",
        epistemic_confidence=0.6,
        contradiction_codes=(),
        runtime_reconciliation=reconciliation,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.mission_runtime_evidence_projection.build_mission_runtime_evidence_projection",
        lambda **_: runtime,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.deliverable_runtime_observability.build_deliverable_runtime_state_read",
        lambda _: runtime_state,
    )
    service = ContinuousAssuranceService(session)
    service._snapshots = MagicMock()
    service._snapshots.latest_for_mission.return_value = None
    service._snapshots.append.side_effect = lambda snapshot: snapshot

    snapshot = service.reconcile_mission(tenant_id="tenant-a", mission=mission)

    assert snapshot.status == "drifted"
    assert snapshot.first_divergence == "task:abc:missing_evidence"
    assert snapshot.finding_count == 1
    assert snapshot.findings[0]["category"] == "semantic_drift"


def test_unchanged_observation_reuses_latest_snapshot(monkeypatch) -> None:
    mission = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id="tenant-a",
        status="completed",
        metadata_json={},
    )
    session = MagicMock()
    session.scalars.side_effect = [[] for _ in range(8)]
    runtime = SimpleNamespace(
        contradictions=[],
        missing_evidence=[],
        first_divergence=None,
        mission_status="completed",
        nodes=[],
        edges=[],
        task_flows=[],
        record_flows=[],
    )
    reconciliation = SimpleNamespace(
        status="aligned",
        semantic_status="aligned",
        semantic_mismatch_codes=(),
        semantic_drift_codes=(),
    )
    runtime_state = SimpleNamespace(
        lifecycle_state="current",
        epistemic_confidence=0.8,
        contradiction_codes=(),
        runtime_reconciliation=reconciliation,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.mission_runtime_evidence_projection.build_mission_runtime_evidence_projection",
        lambda **_: runtime,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.deliverable_runtime_observability.build_deliverable_runtime_state_read",
        lambda _: runtime_state,
    )
    service = ContinuousAssuranceService(session)
    service._snapshots = MagicMock()
    service._snapshots.latest_for_mission.return_value = None
    service._snapshots.append.side_effect = lambda snapshot: snapshot

    first = service.reconcile_mission(tenant_id="tenant-a", mission=mission)
    service._snapshots.latest_for_mission.return_value = first
    second = service.reconcile_mission(tenant_id="tenant-a", mission=mission)

    assert second is first
    assert service._snapshots.append.call_count == 1

def test_artifact_and_semantic_errors_never_report_aligned(monkeypatch) -> None:
    mission = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id="tenant-a",
        status="completed",
        metadata_json={},
    )
    runtime = SimpleNamespace(
        contradictions=[],
        missing_evidence=[],
        first_divergence=None,
        mission_status="completed",
        nodes=[],
        edges=[],
        task_flows=[],
        record_flows=[],
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.mission_runtime_evidence_projection.build_mission_runtime_evidence_projection",
        lambda **_: runtime,
    )
    for artifact_codes, semantic_codes in [
        (("missing_output_contract",), ()),
        ((), ("selection_mismatch",)),
        (("missing_output_contract",), ("selection_mismatch",)),
    ]:
        reconciliation = SimpleNamespace(
            status="aligned",
            semantic_status="aligned",
            semantic_mismatch_codes=semantic_codes,
            semantic_drift_codes=(),
        )
        runtime_state = SimpleNamespace(
            lifecycle_state="current",
            epistemic_confidence=0.9,
            contradiction_codes=artifact_codes,
            runtime_reconciliation=reconciliation,
        )
        monkeypatch.setattr(
            "backend.services.continuous_assurance.deliverable_runtime_observability.build_deliverable_runtime_state_read",
            lambda _, state=runtime_state: state,
        )
        session = MagicMock()
        session.scalars.side_effect = [[], [], [], [], []]
        service = ContinuousAssuranceService(session)
        service._snapshots = MagicMock()
        service._snapshots.latest_for_mission.return_value = None
        service._snapshots.append.side_effect = lambda snapshot: snapshot
        snapshot = service.reconcile_mission(tenant_id="tenant-a", mission=mission)
        assert any(finding["severity"] == "error" for finding in snapshot.findings)
        assert snapshot.status == "contradictory"
        assert snapshot.calibration_outcome_aligned is False


def test_historical_unknown_is_not_misreported_as_current_violation(monkeypatch) -> None:
    mission = SimpleNamespace(
        id=uuid.uuid4(), tenant_id="tenant-a", status="completed", metadata_json={}
    )
    runtime = SimpleNamespace(
        contradictions=[], missing_evidence=["task:old:evidence"],
        historical_unknown=["task:old:evidence"], first_divergence=None,
        mission_status="completed", nodes=[], edges=[], task_flows=[], record_flows=[],
    )
    runtime_state = SimpleNamespace(
        lifecycle_state="current", epistemic_confidence=0.8,
        contradiction_codes=(), runtime_reconciliation=None,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.mission_runtime_evidence_projection.build_mission_runtime_evidence_projection",
        lambda **_: runtime,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.deliverable_runtime_observability.build_deliverable_runtime_state_read",
        lambda _: runtime_state,
    )
    session = MagicMock()
    session.scalars.side_effect = [[], [], [], [], []]
    service = ContinuousAssuranceService(session)
    service._snapshots = MagicMock()
    service._snapshots.latest_for_mission.return_value = None
    service._snapshots.append.side_effect = lambda snapshot: snapshot
    snapshot = service.reconcile_mission(tenant_id="tenant-a", mission=mission)
    assert snapshot.status == "incomplete"
    assert snapshot.findings == [
        {"category": "historical_unknown", "code": "task:old:evidence", "severity": "info"}
    ]
    assert snapshot.runtime_summary["historical_unknown_count"] == 1


def test_actual_runtime_projection_drives_assurance_from_independent_fixture(monkeypatch) -> None:
    """Use the real projection, not a mocked projection asserting its own result."""
    mission_id = uuid.uuid4()
    task_id = uuid.uuid4()
    lease_id = uuid.uuid4()
    mission = SimpleNamespace(
        id=mission_id,
        tenant_id="tenant-a",
        status="completed",
        metadata_json={
            "runtime_task_materialization": {"created_execution_task_ids": [str(task_id)]},
            "runtime_queue_admission": {"admitted_execution_task_ids": [str(task_id)]},
        },
    )
    task = SimpleNamespace(
        id=task_id, mission_id=mission_id, tenant_id="tenant-a",
        status="completed", metadata_json={"runtime_evidence_contract_version": "1"},
    )
    lease = SimpleNamespace(
        id=lease_id, task_id=task_id, tenant_id="tenant-a",
        status="released", holder_identity="worker-a",
    )
    runtime_state = SimpleNamespace(
        lifecycle_state="current", epistemic_confidence=0.8,
        contradiction_codes=(), runtime_reconciliation=None,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.deliverable_runtime_observability.build_deliverable_runtime_state_read",
        lambda _: runtime_state,
    )
    session = MagicMock()
    start_event = SimpleNamespace(
        id=uuid.uuid4(), tenant_id="tenant-a", mission_id=mission_id,
        category="mission_information", action="execution_started",
        actor="worker-a", details="observed", created_at=datetime.now(UTC),
        payload_json={
            "schema_version": 1, "task_id": str(task_id),
            "lease_id": str(lease_id), "grants_execution_authority": False,
        },
    )
    session.scalars.side_effect = [[task], [lease], [], [], [start_event]]
    service = ContinuousAssuranceService(session)
    service._snapshots = MagicMock()
    service._snapshots.latest_for_mission.return_value = None
    service._snapshots.append.side_effect = lambda snapshot: snapshot

    snapshot = service.reconcile_mission(tenant_id="tenant-a", mission=mission)

    assert snapshot.status == "contradictory"
    assert snapshot.findings == [
        {
            "category": "runtime_contradiction",
            "code": f"task:{task_id}:completed_without_evidence",
            "severity": "error",
        },
        {
            "category": "missing_evidence",
            "code": f"task:{task_id}:evidence",
            "severity": "warning",
        },
    ]


def test_assurance_security_verdict_is_independent_of_operational_alignment(monkeypatch) -> None:
    mission_id = uuid.uuid4()
    mission = SimpleNamespace(
        id=mission_id, tenant_id="tenant-a", status="planned", metadata_json={},
    )
    foreign_task = SimpleNamespace(
        id=uuid.uuid4(), tenant_id="tenant-b", mission_id=mission_id,
        status="planned", metadata_json={},
    )
    runtime = SimpleNamespace(
        contradictions=[], missing_evidence=[], historical_unknown=[],
        first_divergence=None, mission_status="planned",
        nodes=[], edges=[], task_flows=[], record_flows=[],
    )
    runtime_state = SimpleNamespace(
        lifecycle_state="current", epistemic_confidence=None,
        contradiction_codes=(), runtime_reconciliation=None,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.mission_runtime_evidence_projection.build_mission_runtime_evidence_projection",
        lambda **_: runtime,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.deliverable_runtime_observability.build_deliverable_runtime_state_read",
        lambda _: runtime_state,
    )
    session = MagicMock()
    session.scalars.side_effect = [[foreign_task], [], [], [], []]
    service = ContinuousAssuranceService(session)
    service._snapshots = MagicMock()
    service._snapshots.latest_for_mission.return_value = None
    service._snapshots.append.side_effect = lambda snapshot: snapshot
    snapshot = service.reconcile_mission(tenant_id="tenant-a", mission=mission)

    assert snapshot.runtime_summary["security_status"] == "alert"
    assert snapshot.runtime_summary["security_finding_count"] == 1
    assert any(item["category"] == "security_tenant_boundary" for item in snapshot.findings)
    assert snapshot.grants_execution_authority is False
