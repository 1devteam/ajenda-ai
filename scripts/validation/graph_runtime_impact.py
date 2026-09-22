#!/usr/bin/env python3
"""Join static GRAFT impact with one persisted runtime evidence projection.

This module only exposes facts.  It deliberately does not decide whether a
change is safe, applicable, or authorized.  The evaluator consumes the
artifact and reasons about blast radius from the cited facts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _node_key(item: dict[str, Any]) -> str | None:
    value = item.get("node_key") or item.get("key") or item.get("id")
    return str(value) if value else None


def _nested_strings(value: Any) -> list[str]:
    """Collect strings from a runtime snapshot without interpreting them."""

    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_nested_strings(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_nested_strings(item))
        return result
    return []


def _runtime_consistency_facts(
    runtime_projection: dict[str, Any], task_flows: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """Expose contradictions and unproven artifact links in a runtime snapshot."""

    contradictions: set[str] = set()
    artifact_linkage_gaps: set[str] = set()
    for flow in task_flows:
        task_id = str(flow.get("task_id") or flow.get("node_key") or "unknown")
        if flow.get("status") != "completed":
            continue
        declared = flow.get("declared_output_contract")
        contract_key = declared.get("artifact") if isinstance(declared, dict) else None
        observed = flow.get("observed_output_keys")
        if contract_key and isinstance(observed, list) and contract_key in observed and not flow.get("artifact_ids"):
            artifact_linkage_gaps.add(f"task:{task_id}:output_without_artifact_identity:{contract_key}")

    queue_admitted = any(
        isinstance(flow.get("queue_admitted"), bool) and flow.get("queue_admitted") for flow in task_flows
    )
    stale_admission_text = any(
        "no runtime work was queued or dispatched" in text.lower() for text in _nested_strings(runtime_projection)
    )
    if queue_admitted and stale_admission_text:
        contradictions.add("runtime_admission_summary_conflicts_with_observed_queue_execution")

    mission_status = str(runtime_projection.get("mission_status") or "").lower()
    acceptance = runtime_projection.get("acceptance")
    acceptance_status = str(acceptance.get("status") or "").lower() if isinstance(acceptance, dict) else ""
    if mission_status == "completed" and acceptance_status not in {"", "met", "satisfied", "complete", "completed"}:
        contradictions.add("mission_completed_with_nonterminal_acceptance_status")
    if mission_status in {"failed", "blocked"} and acceptance_status in {"met", "satisfied", "complete", "completed"}:
        contradictions.add("mission_failed_with_satisfied_acceptance_status")
    return sorted(contradictions), sorted(artifact_linkage_gaps)


def _static_nodes(impact: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for section, relation in (
        ("changed_nodes", "changed"),
        ("upstream_consumers", "upstream_consumer"),
        ("downstream_dependencies", "downstream_dependency"),
        ("affected_semantic_nodes", "affected_semantic"),
        ("dependency_semantic_nodes", "dependency_semantic"),
    ):
        for item in _dicts(impact.get(section)):
            node_id = _node_key(item)
            if node_id is None:
                continue
            nodes.append(
                {
                    "id": node_id,
                    "relation": relation,
                    "type": item.get("type"),
                    "source": item.get("source"),
                    "label": item.get("label"),
                    "distance": item.get("distance"),
                    "provenance": "static_graph_impact",
                }
            )
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in nodes:
        unique[(item["id"], item["relation"])] = item
    return sorted(unique.values(), key=lambda item: (item["id"], item["relation"]))


def build_runtime_impact_artifact(
    *, impact_report: dict[str, Any], runtime_projection: dict[str, Any]
) -> dict[str, Any]:
    """Return a source-backed static/runtime impact artifact."""

    available = _dicts(runtime_projection.get("available_nodes"))
    selected = _dicts(runtime_projection.get("selected_nodes"))
    task_flows = _dicts(runtime_projection.get("task_flows"))
    available_keys = {key for item in available if (key := _node_key(item))}
    selected_keys = {key for item in selected if (key := _node_key(item))}
    observed_keys = {key for item in task_flows if (key := _node_key(item)) and item.get("status") is not None}
    unobserved_selected = sorted(selected_keys - observed_keys)
    static_nodes = _static_nodes(impact_report)
    runtime_nodes = [
        {
            "id": key,
            "relation": "runtime_observed",
            "provenance": "mission_runtime_evidence",
        }
        for key in sorted(observed_keys)
    ]
    runtime_unobserved = [
        {
            "id": key,
            "relation": "runtime_selected_unobserved",
            "provenance": "mission_runtime_evidence",
        }
        for key in unobserved_selected
    ]
    contradictions = sorted(str(item) for item in runtime_projection.get("contradictions", []) if item)
    missing = sorted(str(item) for item in runtime_projection.get("missing_evidence", []) if item)
    consistency_contradictions, artifact_linkage_gaps = _runtime_consistency_facts(runtime_projection, task_flows)
    contradictions = sorted(set(contradictions) | set(consistency_contradictions))

    # These are evidence gaps, not judgments.  They identify facts the
    # supplied snapshots cannot establish.
    unknowns = []
    if not impact_report:
        unknowns.append("static_graph_impact_report")
    if not runtime_projection:
        unknowns.append("mission_runtime_evidence_projection")
    if selected_keys and not task_flows:
        unknowns.append("selected_runtime_nodes_without_task_flows")
    if available_keys and not selected_keys:
        unknowns.append("available_runtime_nodes_without_selection_snapshot")

    payload = {
        "schema_version": "1.0",
        "scope": "graft-static-runtime-impact",
        "read_only": True,
        "grants_execution_authority": False,
        "static": {
            "graph_sha256": impact_report.get("graph_sha256"),
            "changed_files": list(impact_report.get("changed_files") or []),
            "nodes": static_nodes,
            "impacted_tests": _dicts(impact_report.get("impacted_tests")),
            "relevant_invariants": _dicts(impact_report.get("relevant_invariants")),
            "risk_domains": _dicts(impact_report.get("risk_domains")),
        },
        "runtime": {
            "mission_id": runtime_projection.get("mission_id"),
            "tenant_id": runtime_projection.get("tenant_id"),
            "mission_status": runtime_projection.get("mission_status"),
            "acceptance": runtime_projection.get("acceptance") or {},
            "observed_nodes": runtime_nodes,
            "selected_unobserved_nodes": runtime_unobserved,
            "task_flow_count": len(task_flows),
            "contradictions": contradictions,
            "artifact_linkage_gaps": artifact_linkage_gaps,
            "missing_evidence": missing,
            "first_divergence": runtime_projection.get("first_divergence"),
        },
        "facts": {
            "static_affected_nodes": static_nodes,
            "runtime_observed_nodes": runtime_nodes,
            "runtime_unobserved_selected_nodes": runtime_unobserved,
            "contradictions": contradictions,
            "artifact_linkage_gaps": artifact_linkage_gaps,
            "missing_evidence": missing,
            "unknowns": sorted(set(unknowns)),
            "mission_status": runtime_projection.get("mission_status"),
            "acceptance": runtime_projection.get("acceptance") or {},
        },
        "provenance": {
            "static_source": "graph_impact_analysis",
            "runtime_source": "mission_runtime_evidence_projection",
            "static_schema_version": impact_report.get("schema_version"),
            "runtime_schema_version": runtime_projection.get("schema_version"),
        },
    }
    payload["artifact_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--impact-report", type=Path, required=True)
    parser.add_argument("--runtime-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    impact = json.loads(args.impact_report.read_text(encoding="utf-8"))
    runtime = json.loads(args.runtime_evidence.read_text(encoding="utf-8"))
    if not isinstance(impact, dict) or not isinstance(runtime, dict):
        raise ValueError("impact and runtime inputs must each contain one JSON object")
    artifact = build_runtime_impact_artifact(impact_report=impact, runtime_projection=runtime)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    facts = artifact["facts"]
    print(
        "GRAFT static/runtime impact: "
        f"{len(facts['static_affected_nodes'])} static node(s), "
        f"{len(facts['runtime_observed_nodes'])} observed runtime node(s), "
        f"{len(facts['runtime_unobserved_selected_nodes'])} unobserved selected node(s), "
        f"{len(facts['contradictions'])} contradiction(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
