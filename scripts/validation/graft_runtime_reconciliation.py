#!/usr/bin/env python3
"""Reconcile one runtime artifact chain from graph expectation to deliverable.

The command consumes an exported, tenant-scoped runtime snapshot.  It never
queries or mutates runtime state and never fabricates missing stages.  Missing
or contradictory lineage is reported as a finding and causes a non-zero exit
until the snapshot explicitly marks the finding resolved with an explanation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# Keep the validator executable both as a module and as a repository-rooted
# script without duplicating the canonical semantic contract.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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


STAGES = (
    "selected_nodes",
    "materialized_tasks",
    "queued_tasks",
    "evidence_nodes",
    "deliverable_nodes",
)


def reconcile_snapshot(snapshot: RuntimeReconciliationSnapshot) -> dict[str, Any]:
    findings = list(snapshot.findings)
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
        "stage_counts": {stage_name: len(getattr(snapshot, stage_name)) for stage_name in STAGES},
        "semantic_reconciliation": (
            "not_available"
            if snapshot.semantic_selection is None
            else "blocked"
            if snapshot.semantic_selection.conflicts
            else "aligned"
        ),
        "finding_count": len(findings),
        "unresolved_finding_count": len(unresolved),
        "status": "passed" if not unresolved else "blocked",
        "findings": [finding.model_dump(mode="json") for finding in findings],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Tenant-scoped exported reconciliation snapshot JSON")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        snapshot = RuntimeReconciliationSnapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        print(f"FAIL: invalid reconciliation snapshot: {exc}")
        return 1
    report = reconcile_snapshot(snapshot)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(f"Runtime reconciliation: {report['status']} ({report['unresolved_finding_count']} unresolved findings)")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
