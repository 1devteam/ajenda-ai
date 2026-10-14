"""Shared, read-only G.R.A.F.T. runtime reconciliation snapshot contract."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.services.mission_composition.semantic_vocabulary import SemanticSelection


class RuntimeStage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_key: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=80)


class ReconciliationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    resolved: bool = False
    resolution: str | None = Field(default=None, max_length=1000)


class SnapshotProvenance(BaseModel):
    """Capture metadata; a digest detects alteration, not dishonest producers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    captured_at: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    producer_version: str = Field(min_length=1)
    source_record_ids: tuple[str, ...] = Field(min_length=1)
    evidence_contract_version: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class RuntimeReconciliationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    tenant_id: str = Field(min_length=1, max_length=160)
    mission_id: str = Field(min_length=1, max_length=160)
    graph_expected_nodes: tuple[str, ...] = Field(min_length=1, max_length=500)
    selected_nodes: tuple[RuntimeStage, ...] = ()
    materialized_tasks: tuple[RuntimeStage, ...] = ()
    queued_tasks: tuple[RuntimeStage, ...] = ()
    evidence_nodes: tuple[RuntimeStage, ...] = ()
    deliverable_nodes: tuple[RuntimeStage, ...] = ()
    semantic_selection: SemanticSelection | None = None
    findings: tuple[ReconciliationFinding, ...] = ()
    provenance: SnapshotProvenance | None = None


def snapshot_digest(snapshot: RuntimeReconciliationSnapshot) -> str:
    """Digest the entire exported payload except the self-referential digest."""
    payload = snapshot.model_dump(mode="json", exclude={"provenance": {"sha256"}})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def seal_snapshot(
    snapshot: RuntimeReconciliationSnapshot,
    *,
    producer: str,
    producer_version: str,
    source_record_ids: tuple[str, ...],
    evidence_contract_version: str,
) -> RuntimeReconciliationSnapshot:
    """Create an internally consistent export; source trust is checked separately."""
    if snapshot.provenance is not None:
        raise ValueError("snapshot is already sealed")
    provenance = SnapshotProvenance(
        captured_at=datetime.now(UTC).isoformat(),
        producer=producer,
        producer_version=producer_version,
        source_record_ids=source_record_ids,
        evidence_contract_version=evidence_contract_version,
        sha256="sha256:" + "0" * 64,
    )
    unsealed = snapshot.model_copy(update={"provenance": provenance})
    digest = snapshot_digest(unsealed)
    return unsealed.model_copy(update={"provenance": provenance.model_copy(update={"sha256": digest})})


STAGES = (
    "selected_nodes",
    "materialized_tasks",
    "queued_tasks",
    "evidence_nodes",
    "deliverable_nodes",
)


def reconcile_snapshot(snapshot: RuntimeReconciliationSnapshot) -> dict[str, Any]:
    findings = list(snapshot.findings)
    provenance_status = "legacy_unverified"
    if snapshot.provenance is not None:
        provenance_status = "digest_verified"
        if snapshot_digest(snapshot) != snapshot.provenance.sha256:
            provenance_status = "digest_mismatch"
            findings.append(
                ReconciliationFinding(
                    finding_id="snapshot.provenance_digest_mismatch",
                    category="provenance",
                    message="Snapshot content does not match its declared capture digest.",
                )
            )
    if snapshot.semantic_selection is not None:
        if snapshot.semantic_selection.conflicts:
            findings.append(
                ReconciliationFinding(
                    finding_id="semantic.selection_conflict",
                    category="semantic",
                    message=(
                        "Semantic concept-to-job selection contains unresolved conflicts: "
                        f"{list(snapshot.semantic_selection.conflicts)}"
                    ),
                )
            )
        for binding in snapshot.semantic_selection.bindings:
            if binding.status == "conflict":
                findings.append(
                    ReconciliationFinding(
                        finding_id=f"semantic.binding.{binding.concept_id}",
                        category="semantic",
                        message=(
                            f"Semantic concept {binding.concept_id} was not reconciled with its "
                            f"expected jobs {list(binding.expected_job_keys)}."
                        ),
                    )
                )
    expected = set(snapshot.graph_expected_nodes)
    if len(expected) != len(snapshot.graph_expected_nodes):
        findings.append(
            ReconciliationFinding(
                finding_id="graph.duplicate_expected_node",
                category="graph",
                message="Graph expectation contains duplicate node keys.",
            )
        )

    previous = expected
    for stage_name in STAGES:
        stage = getattr(snapshot, stage_name)
        ids = [item.node_key for item in stage]
        current = set(ids)
        if len(current) != len(ids):
            findings.append(
                ReconciliationFinding(
                    finding_id=f"{stage_name}.duplicate_node",
                    category="lineage",
                    message=f"{stage_name} contains duplicate node keys.",
                )
            )
        missing = sorted(previous - current)
        if missing:
            findings.append(
                ReconciliationFinding(
                    finding_id=f"{stage_name}.missing_upstream_nodes",
                    category="lineage",
                    message=f"{stage_name} dropped upstream nodes: {missing}",
                )
            )
        unexpected = sorted(current - previous)
        if unexpected:
            findings.append(
                ReconciliationFinding(
                    finding_id=f"{stage_name}.undeclared_node",
                    category="authority",
                    message=f"{stage_name} introduced nodes not present upstream: {unexpected}",
                )
            )
        previous = current

        wrong_tenant = sorted({item.node_key for item in stage if item.tenant_id != snapshot.tenant_id})
        if wrong_tenant:
            findings.append(
                ReconciliationFinding(
                    finding_id=f"{stage_name}.tenant_mismatch",
                    category="tenant_scope",
                    message=f"{stage_name} contains nodes from another tenant: {wrong_tenant}",
                )
            )

    unresolved = [finding for finding in findings if not finding.resolved]
    return {
        "schema_version": 1,
        "tenant_id": snapshot.tenant_id,
        "mission_id": snapshot.mission_id,
        "provenance_status": provenance_status,
        "source_authenticity_verified": False,
        "stage_counts": {stage_name: len(getattr(snapshot, stage_name)) for stage_name in STAGES},
        "semantic_reconciliation": (
            "not_available"
            if snapshot.semantic_selection is None
            else "blocked"
            if snapshot.semantic_selection.conflicts
            or any(binding.status == "conflict" for binding in snapshot.semantic_selection.bindings)
            else "aligned"
        ),
        "finding_count": len(findings),
        "unresolved_finding_count": len(unresolved),
        "status": "passed" if not unresolved else "blocked",
        "findings": [finding.model_dump(mode="json") for finding in findings],
    }

