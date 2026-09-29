from scripts.validation.graft_runtime_reconciliation import (
    RuntimeReconciliationSnapshot,
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
