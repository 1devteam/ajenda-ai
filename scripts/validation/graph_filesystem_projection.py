#!/usr/bin/env python3
"""Project graph-backed filesystem groupings without moving source files.

This interpreter consumes Ajenda's canonical dependency graph and emits a
machine artifact describing where currently-flat backend/services modules have
strong structural affinity with existing service packages.

It is deliberately non-mutating:
- no file moves
- no import rewrites
- no runtime authority
- no merge authority

The output is intended for an LLM or follow-on tooling to decide whether a
bounded reorganization is worth materializing, then send the proposed delta
back through GRAFT impact/proof analysis.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from build_dependency_graph import build_graph
from graph_completeness_audit import architectural_boundary, audit_graph

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = "backend/services/"
STATIC_EDGE_TYPES = {"imports", "calls_function", "defines_function"}
TEST_EDGE_TYPES = {"tests", "tests_function"}
AUTHORITY_NODE_TYPES = {
    "runtime",
    "security_boundary",
    "state_resource",
    "network_egress_sink",
    "runtime_support",
}
EDGE_WEIGHT = {
    "imports": 6,
    "calls_function": 5,
    "defines_function": 1,
    "selects_action": 4,
    "implements_action": 4,
    "supports_runtime": 4,
    "reads_state": 4,
    "writes_state": 5,
    "claims_state": 5,
    "emits": 3,
    "consumes": 3,
}


def _source(node: dict[str, Any]) -> str:
    return str(node.get("source") or "").replace("\\", "/")


def _service_package(source: str) -> str | None:
    if not source.startswith(SERVICE_ROOT):
        return None
    remainder = source[len(SERVICE_ROOT):]
    parts = [part for part in remainder.split("/") if part]
    if len(parts) < 2:
        return None
    return parts[0]


def _is_flat_service(source: str) -> bool:
    if not source.startswith(SERVICE_ROOT) or not source.endswith(".py"):
        return False
    remainder = source[len(SERVICE_ROOT):]
    return "/" not in remainder and remainder != "__init__.py"


def _node_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): node for node in graph.get("nodes", [])}


def _source_nodes(graph: dict[str, Any]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    for node in graph.get("nodes", []):
        source = _source(node)
        if source:
            index[source].append(str(node["id"]))
    return {source: sorted(ids) for source, ids in index.items()}


def _metric_map(audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in audit.get("node_metrics", [])}


def _incident_edges(graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", []):
        source = str(edge.get("from"))
        target = str(edge.get("to"))
        result[source].append(edge)
        result[target].append(edge)
    return result


def _test_reach(graph: dict[str, Any]) -> dict[str, list[str]]:
    tests: dict[str, set[str]] = defaultdict(set)
    for edge in graph.get("edges", []):
        if str(edge.get("type")) not in TEST_EDGE_TYPES:
            continue
        source = str(edge.get("from"))
        target = str(edge.get("to"))
        if source.startswith("test:"):
            tests[target].add(source)
        if target.startswith("test:"):
            tests[source].add(target)
    return {node_id: sorted(values) for node_id, values in tests.items()}


def _cycle_membership(audit: dict[str, Any]) -> dict[str, list[int]]:
    membership: dict[str, list[int]] = defaultdict(list)
    for index, cycle in enumerate(audit.get("static_cycles", [])):
        for node_id in cycle.get("nodes", []):
            membership[str(node_id)].append(index)
    return dict(membership)


def _package_members(graph: dict[str, Any]) -> dict[str, set[str]]:
    packages: dict[str, set[str]] = defaultdict(set)
    for node in graph.get("nodes", []):
        package = _service_package(_source(node))
        if package:
            packages[package].add(str(node["id"]))
    return dict(packages)


def _edge_weight(edge_type: str) -> int:
    if edge_type in TEST_EDGE_TYPES:
        return 0
    return EDGE_WEIGHT.get(edge_type, 2)


def _affinity(
    node_id: str,
    *,
    nodes: dict[str, dict[str, Any]],
    incident: dict[str, list[dict[str, Any]]],
    packages: dict[str, set[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scores: Counter[str] = Counter()
    evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    node_packages = {
        member_id: package
        for package, members in packages.items()
        for member_id in members
    }

    for edge in incident.get(node_id, []):
        edge_type = str(edge.get("type") or "")
        weight = _edge_weight(edge_type)
        if not weight:
            continue
        other = str(edge.get("to")) if str(edge.get("from")) == node_id else str(edge.get("from"))
        package = node_packages.get(other)
        if package is None:
            other_source = _source(nodes.get(other, {}))
            package = _service_package(other_source)
        if package is None:
            continue
        scores[package] += weight
        evidence[package].append(
            {
                "edge_type": edge_type,
                "from": str(edge.get("from")),
                "to": str(edge.get("to")),
                "evidence": edge.get("evidence"),
                "weight": weight,
            }
        )

    ranked = [
        {
            "package": package,
            "score": score,
            "edge_count": len(evidence[package]),
        }
        for package, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ]
    flattened = [
        {"package": package, **item}
        for package in sorted(evidence)
        for item in sorted(
            evidence[package],
            key=lambda row: (-int(row["weight"]), str(row["edge_type"]), str(row["from"]), str(row["to"])),
        )
    ]
    return ranked, flattened


def _risk(
    node_id: str,
    *,
    metric: dict[str, Any],
    cycles: dict[str, list[int]],
    tests: dict[str, list[str]],
    incident: dict[str, list[dict[str, Any]]],
    nodes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    authority_edges: list[dict[str, Any]] = []
    for edge in incident.get(node_id, []):
        other_id = str(edge.get("to")) if str(edge.get("from")) == node_id else str(edge.get("from"))
        other = nodes.get(other_id, {})
        if str(other.get("type")) in AUTHORITY_NODE_TYPES:
            authority_edges.append(
                {
                    "node": other_id,
                    "node_type": other.get("type"),
                    "edge_type": edge.get("type"),
                    "evidence": edge.get("evidence"),
                }
            )

    transitive_consumers = int(metric.get("transitive_consumers") or 0)
    direct_consumers = int(metric.get("direct_consumers") or 0)
    direct_dependencies = int(metric.get("direct_dependencies") or 0)
    betweenness = float(metric.get("betweenness") or 0.0)
    cycle_count = len(cycles.get(node_id, []))
    test_count = len(tests.get(node_id, []))

    risk_score = (
        min(transitive_consumers, 500)
        + direct_consumers * 4
        + direct_dependencies * 2
        + round(betweenness * 1000)
        + cycle_count * 40
        + len(authority_edges) * 50
    )

    return {
        "score": risk_score,
        "direct_consumers": direct_consumers,
        "direct_dependencies": direct_dependencies,
        "transitive_consumers": transitive_consumers,
        "transitive_dependencies": int(metric.get("transitive_dependencies") or 0),
        "betweenness": betweenness,
        "static_cycle_ids": cycles.get(node_id, []),
        "impacted_test_count": test_count,
        "authority_sensitive": bool(authority_edges),
        "authority_edges": authority_edges,
    }


def _disposition(ranked: list[dict[str, Any]], risk: dict[str, Any]) -> dict[str, Any]:
    if not ranked:
        return {
            "status": "retain",
            "reason": "no_existing_package_affinity",
            "candidate_package": None,
        }
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    margin = int(best["score"]) - int(second["score"]) if second else int(best["score"])
    if int(best["score"]) < 6:
        status = "retain"
        reason = "weak_graph_affinity"
    elif second and margin < 4:
        status = "ambiguous"
        reason = "competing_package_affinity"
    elif risk["authority_sensitive"] or risk["static_cycle_ids"]:
        status = "candidate_requires_proof"
        reason = "graph_affinity_with_authority_or_cycle_risk"
    else:
        status = "move_candidate"
        reason = "dominant_existing_package_affinity"
    return {
        "status": status,
        "reason": reason,
        "candidate_package": best["package"],
        "candidate_score": best["score"],
        "runner_up_package": second["package"] if second else None,
        "runner_up_score": second["score"] if second else None,
        "score_margin": margin,
    }


def build_projection() -> dict[str, Any]:
    graph = build_graph()
    audit = audit_graph(graph)
    nodes = _node_map(graph)
    by_source = _source_nodes(graph)
    metrics = _metric_map(audit)
    incident = _incident_edges(graph)
    packages = _package_members(graph)
    tests = _test_reach(graph)
    cycles = _cycle_membership(audit)

    candidates: list[dict[str, Any]] = []
    for source in sorted(path for path in by_source if _is_flat_service(path)):
        source_node_ids = [
            node_id
            for node_id in by_source[source]
            if str(nodes.get(node_id, {}).get("type")) not in {"test_module", "graph_tooling_module"}
        ]
        if not source_node_ids:
            continue

        primary = max(
            source_node_ids,
            key=lambda node_id: (
                int(metrics.get(node_id, {}).get("semantic_incident_edges") or 0),
                int(metrics.get(node_id, {}).get("direct_consumers") or 0)
                + int(metrics.get(node_id, {}).get("direct_dependencies") or 0),
                node_id,
            ),
        )
        ranked, affinity_evidence = _affinity(
            primary,
            nodes=nodes,
            incident=incident,
            packages=packages,
        )
        risk = _risk(
            primary,
            metric=metrics.get(primary, {}),
            cycles=cycles,
            tests=tests,
            incident=incident,
            nodes=nodes,
        )
        disposition = _disposition(ranked, risk)
        candidates.append(
            {
                "source": source,
                "primary_node": primary,
                "current_boundary": architectural_boundary(nodes[primary]),
                "all_source_nodes": source_node_ids,
                "package_affinity": ranked,
                "affinity_evidence": affinity_evidence,
                "risk": risk,
                "projection": disposition,
            }
        )

    package_projection: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        package = item["projection"].get("candidate_package")
        if package:
            package_projection[str(package)].append(
                {
                    "source": item["source"],
                    "status": item["projection"]["status"],
                    "affinity_score": item["projection"].get("candidate_score"),
                    "risk_score": item["risk"]["score"],
                }
            )

    return {
        "schema_version": "1.0",
        "artifact_kind": "graft_filesystem_projection",
        "role": "machine_interpretation",
        "source_of_truth": {
            "graph_builder": "scripts/validation/build_dependency_graph.py",
            "completeness_audit": "scripts/validation/graph_completeness_audit.py",
            "graph_schema_version": graph.get("schema_version"),
        },
        "authority": {
            "mutates_source": False,
            "grants_execution_authority": False,
            "grants_merge_authority": False,
            "is_refactor_plan": False,
        },
        "scope": {
            "candidate_surface": "backend/services/*.py",
            "anchor_surface": "backend/services/<existing-package>/**",
            "flat_service_file_count": len(candidates),
            "existing_anchor_package_count": len(packages),
        },
        "graph_metrics": {
            "node_count": graph.get("metrics", {}).get("node_count"),
            "edge_count": graph.get("metrics", {}).get("edge_count"),
            "production_node_count": audit.get("production_node_count"),
            "production_edge_count": audit.get("production_edge_count"),
            "cross_boundary_edge_count": audit.get("cross_boundary_edge_count"),
            "static_cycle_count": len(audit.get("static_cycles", [])),
        },
        "candidate_files": candidates,
        "package_projection": {
            package: sorted(rows, key=lambda row: (-int(row["affinity_score"] or 0), row["source"]))
            for package, rows in sorted(package_projection.items())
        },
        "next_machine_step": {
            "operation": "materialize_candidate_delta_then_rebuild_graph",
            "required_comparison": [
                "cross_boundary_edge_count",
                "static_cycles",
                "top_betweenness",
                "top_transitive_consumers",
                "impacted_tests",
                "semantic_reconciliation",
                "proof_selection",
            ],
            "acceptance_rule": (
                "Do not prefer a filesystem move merely because affinity is high; "
                "accept only when the post-move graph preserves authority semantics, "
                "does not expand cycles, and reduces or preserves structural cost."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    artifact = build_projection()
    rendered = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.as_json or not args.output:
        print(rendered, end="")
    else:
        print(
            "GRAFT filesystem projection: "
            f"{artifact['scope']['flat_service_file_count']} flat service file(s), "
            f"{artifact['scope']['existing_anchor_package_count']} anchor package(s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
