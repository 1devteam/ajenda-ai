from __future__ import annotations

import uuid
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
        "backend.services.continuous_assurance.build_mission_runtime_evidence_projection",
        lambda **_: runtime,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.build_deliverable_runtime_state_read",
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
        "backend.services.continuous_assurance.build_mission_runtime_evidence_projection",
        lambda **_: runtime,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.build_deliverable_runtime_state_read",
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
        "backend.services.continuous_assurance.build_mission_runtime_evidence_projection",
        lambda **_: runtime,
    )
    monkeypatch.setattr(
        "backend.services.continuous_assurance.build_deliverable_runtime_state_read",
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

