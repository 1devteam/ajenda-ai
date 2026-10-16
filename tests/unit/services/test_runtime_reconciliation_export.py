from uuid import uuid4

import pytest

from backend.services.mission_runtime_evidence_projection import MissionRuntimeEvidenceProjection
from backend.services.runtime_reconciliation_export import export_runtime_reconciliation_snapshot
from scripts.validation.graft_runtime_reconciliation import reconcile_snapshot, snapshot_digest


def _projection(*, with_evidence: bool) -> MissionRuntimeEvidenceProjection:
    return MissionRuntimeEvidenceProjection(
        mission_id=uuid4(),
        tenant_id="tenant-a",
        nodes=[],
        edges=[],
        selected_nodes=[{"node_key": "research"}],
        task_flows=[
            {
                "task_id": "task-a",
                "node_key": "research",
                "status": "completed",
                "queue_admitted": True,
                "lease_ids": ["lease-a"],
                "evidence_ids": ["evidence-a"] if with_evidence else [],
                "evidence_collection_statuses": [{"evidence_id": "evidence-a", "collection_status": "collected"}]
                if with_evidence
                else [],
                "declared_output_contract": {"artifact": "research_report"},
                "observed_output_keys": ["research_report"],
            }
        ],
    )


def test_export_binds_live_source_records_and_detects_integrity() -> None:
    snapshot = export_runtime_reconciliation_snapshot(_projection(with_evidence=True))
    assert snapshot.provenance is not None
    assert snapshot.provenance.sha256 == snapshot_digest(snapshot)
    assert "task:task-a" in snapshot.provenance.source_record_ids
    assert "evidence:evidence-a" in snapshot.provenance.source_record_ids
    report = reconcile_snapshot(snapshot)
    assert report["provenance_status"] == "digest_verified"
    assert report["status"] == "passed"
    assert report["source_authenticity_verified"] is False


def test_export_preserves_missing_evidence_as_missing_stage() -> None:
    snapshot = export_runtime_reconciliation_snapshot(_projection(with_evidence=False))
    assert snapshot.evidence_nodes == ()
    assert reconcile_snapshot(snapshot)["status"] == "blocked"


def test_export_does_not_fabricate_selection() -> None:
    projection = MissionRuntimeEvidenceProjection(mission_id=uuid4(), tenant_id="tenant-a", nodes=[], edges=[])
    with pytest.raises(ValueError, match="selected nodes"):
        export_runtime_reconciliation_snapshot(projection)


def test_rejected_evidence_is_referenced_but_does_not_satisfy_stage() -> None:
    projection = _projection(with_evidence=True)
    projection.task_flows[0]["evidence_collection_statuses"] = [
        {"evidence_id": "evidence-a", "collection_status": "rejected"}
    ]
    snapshot = export_runtime_reconciliation_snapshot(projection)
    assert snapshot.evidence_nodes == ()
    assert snapshot.provenance is not None
    assert "evidence:evidence-a" in snapshot.provenance.source_record_ids
    assert reconcile_snapshot(snapshot)["status"] == "blocked"
