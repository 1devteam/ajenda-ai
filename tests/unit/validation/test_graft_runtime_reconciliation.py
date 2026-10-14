from backend.services.mission_composition.semantic_vocabulary import build_semantic_selection
from scripts.validation.graft_runtime_reconciliation import (
    RuntimeReconciliationSnapshot,
    snapshot_digest,
    seal_snapshot,
    reconcile_snapshot,
)


def _stage(node_key: str, tenant_id: str = "tenant-a") -> dict[str, str]:
    return {"node_key": node_key, "tenant_id": tenant_id, "status": "complete"}


def test_runtime_reconciliation_passes_complete_chain() -> None:
    snapshot = RuntimeReconciliationSnapshot.model_validate(
        {
            "tenant_id": "tenant-a",
            "mission_id": "mission-1",
            "graph_expected_nodes": ["research", "qualify"],
            "selected_nodes": [_stage("research"), _stage("qualify")],
            "materialized_tasks": [_stage("research"), _stage("qualify")],
            "queued_tasks": [_stage("research"), _stage("qualify")],
            "evidence_nodes": [_stage("research"), _stage("qualify")],
            "deliverable_nodes": [_stage("research"), _stage("qualify")],
        }
    )

    report = reconcile_snapshot(snapshot)

    assert report["status"] == "passed"
    assert report["unresolved_finding_count"] == 0


def test_runtime_reconciliation_blocks_dropped_or_cross_tenant_nodes() -> None:
    snapshot = RuntimeReconciliationSnapshot.model_validate(
        {
            "tenant_id": "tenant-a",
            "mission_id": "mission-1",
            "graph_expected_nodes": ["research", "qualify"],
            "selected_nodes": [_stage("research"), _stage("qualify")],
            "materialized_tasks": [_stage("research")],
            "queued_tasks": [_stage("research", "tenant-b")],
            "evidence_nodes": [_stage("research", "tenant-b")],
            "deliverable_nodes": [_stage("research", "tenant-b")],
        }
    )

    report = reconcile_snapshot(snapshot)

    assert report["status"] == "blocked"
    assert report["unresolved_finding_count"] >= 2
    assert any(item["category"] == "tenant_scope" for item in report["findings"])


def test_runtime_reconciliation_projects_aligned_semantic_selection() -> None:
    selection = build_semantic_selection(
        instruction="Research prospects.",
        requested_outcomes=("research_prospects",),
        selected_job_keys=("research.discover_prospects",),
    )
    snapshot = RuntimeReconciliationSnapshot.model_validate(
        {
            "tenant_id": "tenant-a",
            "mission_id": "mission-1",
            "graph_expected_nodes": ["research"],
            "selected_nodes": [_stage("research")],
            "materialized_tasks": [_stage("research")],
            "queued_tasks": [_stage("research")],
            "evidence_nodes": [_stage("research")],
            "deliverable_nodes": [_stage("research")],
            "semantic_selection": selection.model_dump(mode="json"),
        }
    )

    report = reconcile_snapshot(snapshot)

    assert report["status"] == "passed"
    assert report["semantic_reconciliation"] == "aligned"


def test_runtime_reconciliation_blocks_semantic_job_conflict() -> None:
    selection = build_semantic_selection(
        instruction="Qualify prospects.",
        requested_outcomes=("qualify_prospects",),
        selected_job_keys=(),
    )
    snapshot = RuntimeReconciliationSnapshot.model_validate(
        {
            "tenant_id": "tenant-a",
            "mission_id": "mission-1",
            "graph_expected_nodes": ["research"],
            "selected_nodes": [_stage("research")],
            "materialized_tasks": [_stage("research")],
            "queued_tasks": [_stage("research")],
            "evidence_nodes": [_stage("research")],
            "deliverable_nodes": [_stage("research")],
            "semantic_selection": selection.model_dump(mode="json"),
        }
    )

    report = reconcile_snapshot(snapshot)

    assert report["status"] == "blocked"
    assert report["semantic_reconciliation"] == "blocked"
    assert any(item["category"] == "semantic" for item in report["findings"])


def test_legacy_snapshot_is_explicitly_unverified() -> None:
    snapshot = RuntimeReconciliationSnapshot.model_validate(
        {"tenant_id": "tenant-a", "mission_id": "mission-1", "graph_expected_nodes": ["research"]}
    )
    report = reconcile_snapshot(snapshot)
    assert report["provenance_status"] == "legacy_unverified"
    assert report["source_authenticity_verified"] is False


def test_export_digest_detects_tampering() -> None:
    base = {
        "tenant_id": "tenant-a",
        "mission_id": "mission-1",
        "graph_expected_nodes": ["research"],
        "provenance": {
            "captured_at": "2026-10-14T10:00:00Z",
            "producer": "ajenda-runtime-export",
            "producer_version": "1",
            "source_record_ids": ["mission-1"],
            "evidence_contract_version": "1",
            "sha256": "sha256:" + "0" * 64,
        },
    }
    unsigned = RuntimeReconciliationSnapshot.model_validate(base)
    base["provenance"]["sha256"] = snapshot_digest(unsigned)
    valid = RuntimeReconciliationSnapshot.model_validate(base)
    assert reconcile_snapshot(valid)["provenance_status"] == "digest_verified"
    assert reconcile_snapshot(valid)["source_authenticity_verified"] is False

    altered = valid.model_copy(update={"mission_id": "different-mission"})
    report = reconcile_snapshot(altered)
    assert report["status"] == "blocked"
    assert report["provenance_status"] == "digest_mismatch"
    assert any(finding["category"] == "provenance" for finding in report["findings"])


def test_seal_snapshot_binds_capture_identity_and_validates_integrity() -> None:
    snapshot = RuntimeReconciliationSnapshot.model_validate(
        {"tenant_id": "tenant-a", "mission_id": "mission-1", "graph_expected_nodes": ["research"]}
    )
    sealed = seal_snapshot(
        snapshot,
        producer="ajenda-runtime",
        producer_version="1",
        source_record_ids=("mission-1",),
        evidence_contract_version="1",
    )
    assert sealed.provenance is not None
    assert sealed.provenance.producer == "ajenda-runtime"
    assert sealed.provenance.sha256 == snapshot_digest(sealed)
    assert reconcile_snapshot(sealed)["provenance_status"] == "digest_verified"
