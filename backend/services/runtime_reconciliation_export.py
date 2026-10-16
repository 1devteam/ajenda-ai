"""Convert a tenant-scoped live runtime projection into a sealed diagnostic export."""

from __future__ import annotations

from backend.services.mission_runtime_evidence_projection import MissionRuntimeEvidenceProjection
from backend.services.runtime_reconciliation_contract import (
    RuntimeReconciliationSnapshot,
    seal_snapshot,
)


def export_runtime_reconciliation_snapshot(
    projection: MissionRuntimeEvidenceProjection,
) -> RuntimeReconciliationSnapshot:
    """Use only observed task/selection/record links; never invent missing stages."""
    selected_keys = tuple(
        str(node.get("node_key") or node.get("key"))
        for node in projection.selected_nodes
        if node.get("node_key") or node.get("key")
    )
    if not selected_keys:
        raise ValueError("cannot export reconciliation without admitted selected nodes")

    tenant_id = projection.tenant_id

    def stage(key: str, status: str) -> dict[str, str]:
        return {"node_key": key, "tenant_id": tenant_id, "status": status}

    selected = [stage(key, "selected") for key in selected_keys]
    materialized = []
    queued = []
    evidenced = []
    delivered = []
    source_record_ids = [f"mission:{projection.mission_id}"]

    for flow in projection.task_flows:
        task_id = str(flow.get("task_id") or "")
        node_key = flow.get("node_key")
        if task_id:
            source_record_ids.append(f"task:{task_id}")
        if not isinstance(node_key, str) or not node_key:
            continue
        current = stage(node_key, str(flow.get("status") or "unknown"))
        materialized.append(current)
        if flow.get("queue_admitted") is True:
            queued.append(current)
        evidence_ids = flow.get("evidence_ids")
        if isinstance(evidence_ids, list):
            source_record_ids.extend(f"evidence:{item}" for item in evidence_ids)
        evidence_statuses = flow.get("evidence_collection_statuses")
        if isinstance(evidence_statuses, list) and any(
            isinstance(item, dict) and item.get("collection_status") in {"collected", "verified"}
            for item in evidence_statuses
        ):
            evidenced.append(current)
        declared = flow.get("declared_output_contract")
        artifact_key = declared.get("artifact") if isinstance(declared, dict) else None
        output_keys = flow.get("observed_output_keys")
        if (
            flow.get("status") == "completed"
            and isinstance(artifact_key, str)
            and isinstance(output_keys, list)
            and artifact_key in output_keys
        ):
            delivered.append(current)
        for lease_id in flow.get("lease_ids") or []:
            source_record_ids.append(f"lease:{lease_id}")

    snapshot = RuntimeReconciliationSnapshot.model_validate(
        {
            "tenant_id": tenant_id,
            "mission_id": str(projection.mission_id),
            "graph_expected_nodes": selected_keys,
            "selected_nodes": selected,
            "materialized_tasks": materialized,
            "queued_tasks": queued,
            "evidence_nodes": evidenced,
            "deliverable_nodes": delivered,
        }
    )
    return seal_snapshot(
        snapshot,
        producer="ajenda.runtime_reconciliation_export",
        producer_version="1",
        source_record_ids=tuple(sorted(set(source_record_ids))),
        evidence_contract_version="mixed_or_unknown",
    )
