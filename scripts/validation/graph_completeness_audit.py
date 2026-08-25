#!/usr/bin/env python3
"""Audit Ajenda's canonical dependency graph for completeness and semantic integrity."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from build_dependency_graph import REPO_ROOT, build_graph

TEST_EDGE_TYPE = "tests"
STATIC_EDGE_TYPE = "imports"
SOURCE_NODE_PREFIXES = ("py:", "fe:")


def architectural_boundary(node: dict[str, Any]) -> str:
    node_type = str(node.get("type", ""))
    explicit = {
        "runtime": "runtime",
        "security_boundary": "security-boundary",
        "external_service": "external",
        "frontend_module": "frontend",
        "test_module": "tests",
        "database_table": "database",
        "migration": "database-migration",
        "network_egress_sink": "external-egress",
        "state_resource": "state-authority",
    }
    if node_type in explicit:
        return explicit[node_type]

    source = str(node.get("source") or "").replace("\\", "/")
    parts = [part for part in source.split("/") if part]
    if not parts:
        return "source:unknown"
    if parts[0] == "backend":
        if len(parts) == 2:
            return "backend:root"
        if len(parts) >= 4 and parts[1] == "services" and parts[2] in {"credentials", "tools"}:
            return f"backend:services:{parts[2]}"
        if len(parts) >= 3 and parts[1] == "services":
            return "backend:services"
        return f"backend:{parts[1]}"
    if parts[0] == "services":
        return f"standalone:{parts[1]}" if len(parts) >= 2 else "standalone:root"
    if parts[0] == "frontend":
        return "frontend"
    return f"source:{parts[0]}"


def _production_nodes(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): node for node in graph["nodes"] if str(node.get("type")) != "test_module"}


def _production_edges(graph: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        edge
        for edge in graph["edges"]
        if str(edge.get("type")) != TEST_EDGE_TYPE and str(edge.get("from")) in nodes and str(edge.get("to")) in nodes
    ]


def _adjacency(
    node_ids: list[str],
    edges: list[dict[str, Any]],
    *,
    reverse: bool = False,
) -> dict[str, set[str]]:
    adjacency = {node_id: set() for node_id in node_ids}
    for edge in edges:
        source, target = str(edge["from"]), str(edge["to"])
        if reverse:
            source, target = target, source
        adjacency[source].add(target)
    return adjacency


def _reachable(start: str, adjacency: dict[str, set[str]]) -> set[str]:
    visited = {start}
    queue: deque[str] = deque([start])
    while queue:
        current = queue.popleft()
        for target in adjacency.get(current, set()):
            if target not in visited:
                visited.add(target)
                queue.append(target)
    visited.remove(start)
    return visited


def _betweenness(node_ids: list[str], adjacency: dict[str, set[str]]) -> dict[str, float]:
    centrality = {node_id: 0.0 for node_id in node_ids}
    for source in node_ids:
        stack: list[str] = []
        predecessors = {node_id: [] for node_id in node_ids}
        shortest_path_count = {node_id: 0.0 for node_id in node_ids}
        shortest_path_count[source] = 1.0
        distance = {node_id: -1 for node_id in node_ids}
        distance[source] = 0
        queue: deque[str] = deque([source])
        while queue:
            current = queue.popleft()
            stack.append(current)
            for target in adjacency[current]:
                if distance[target] < 0:
                    queue.append(target)
                    distance[target] = distance[current] + 1
                if distance[target] == distance[current] + 1:
                    shortest_path_count[target] += shortest_path_count[current]
                    predecessors[target].append(current)
        dependency = {node_id: 0.0 for node_id in node_ids}
        while stack:
            target = stack.pop()
            if shortest_path_count[target]:
                coefficient = (1.0 + dependency[target]) / shortest_path_count[target]
                for predecessor in predecessors[target]:
                    dependency[predecessor] += shortest_path_count[predecessor] * coefficient
            if target != source:
                centrality[target] += dependency[target]
    if len(node_ids) > 2:
        normalization = float((len(node_ids) - 1) * (len(node_ids) - 2))
        centrality = {node_id: value / normalization for node_id, value in centrality.items()}
    return centrality


def _node_metrics(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node_ids = sorted(nodes)
    forward = _adjacency(node_ids, edges)
    reverse = _adjacency(node_ids, edges, reverse=True)
    betweenness = _betweenness(node_ids, forward)
    direct_consumers = Counter(str(edge["to"]) for edge in edges)
    direct_dependencies = Counter(str(edge["from"]) for edge in edges)
    semantic_incident = Counter()
    for edge in edges:
        if str(edge["type"]) != STATIC_EDGE_TYPE:
            semantic_incident[str(edge["from"])] += 1
            semantic_incident[str(edge["to"])] += 1
    return [
        {
            "id": node_id,
            "boundary": architectural_boundary(nodes[node_id]),
            "direct_consumers": direct_consumers[node_id],
            "direct_dependencies": direct_dependencies[node_id],
            "transitive_consumers": len(_reachable(node_id, reverse)),
            "transitive_dependencies": len(_reachable(node_id, forward)),
            "betweenness": round(betweenness[node_id], 8),
            "semantic_incident_edges": semantic_incident[node_id],
        }
        for node_id in node_ids
    ]


def _boundary_matrix(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for edge in edges:
        source_boundary = architectural_boundary(nodes[str(edge["from"])])
        target_boundary = architectural_boundary(nodes[str(edge["to"])])
        counts[(source_boundary, target_boundary)][str(edge["type"])] += 1
    return [
        {
            "from": source,
            "to": target,
            "count": sum(edge_types.values()),
            "edge_types": dict(sorted(edge_types.items())),
            "cross_boundary": source != target,
        }
        for (source, target), edge_types in sorted(counts.items())
    ]


def _classify_cycles(graph: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for cycle in graph.get("metrics", {}).get("static_cycles", []):
        members = [str(node_id) for node_id in cycle if str(node_id) in nodes]
        boundaries = sorted({architectural_boundary(nodes[node_id]) for node_id in members})
        result.append(
            {
                "nodes": members,
                "boundaries": boundaries,
                "classification": "cross-boundary" if len(boundaries) > 1 else "intra-boundary",
            }
        )
    return result


def _semantic_reconciliation(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    static_edges = [edge for edge in edges if str(edge["type"]) == STATIC_EDGE_TYPE]
    static_adjacency = _adjacency(sorted(nodes), static_edges)
    reconciled: list[dict[str, Any]] = []
    for edge in edges:
        edge_type = str(edge["type"])
        if edge_type == STATIC_EDGE_TYPE:
            continue
        source, target = str(edge["from"]), str(edge["to"])
        source_backed = source.startswith(SOURCE_NODE_PREFIXES)
        target_backed = target.startswith(SOURCE_NODE_PREFIXES)
        if source_backed and target_backed:
            classification = (
                "static-corroborated" if target in _reachable(source, static_adjacency) else "semantic-only"
            )
        else:
            classification = "boundary-or-external"
        reconciled.append(
            {
                "from": source,
                "to": target,
                "type": edge_type,
                "evidence": edge.get("evidence"),
                "classification": classification,
            }
        )
    return sorted(
        reconciled,
        key=lambda item: (str(item["classification"]), str(item["from"]), str(item["to"]), str(item["type"])),
    )


def _missing_evidence(graph: dict[str, Any]) -> tuple[list[str], list[str]]:
    missing_edge_evidence: set[str] = set()
    missing_invariant_sources: set[str] = set()
    for edge in graph.get("edges", []):
        if str(edge.get("type")) in {STATIC_EDGE_TYPE, TEST_EDGE_TYPE}:
            continue
        evidence = edge.get("evidence")
        if not isinstance(evidence, str) or not evidence:
            missing_edge_evidence.add(f"{edge.get('from')}->{edge.get('to')}:{edge.get('type')}:<missing>")
        elif not (REPO_ROOT / evidence).exists():
            missing_edge_evidence.add(evidence)
    for invariant in graph.get("invariants", []):
        for source in invariant.get("sources", []):
            if isinstance(source, str) and source and not (REPO_ROOT / source).exists():
                missing_invariant_sources.add(source)
    return sorted(missing_edge_evidence), sorted(missing_invariant_sources)


def audit_graph(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = _production_nodes(graph)
    edges = _production_edges(graph, nodes)
    metrics = _node_metrics(nodes, edges)
    boundary_matrix = _boundary_matrix(nodes, edges)
    reconciliation = _semantic_reconciliation(nodes, edges)
    cycles = _classify_cycles(graph, nodes)
    missing_edge_evidence, missing_invariant_sources = _missing_evidence(graph)
    findings = [dict(item) for item in graph.get("semantic_findings", [])]
    unacknowledged_blocking = sorted(
        str(item["id"]) for item in findings if bool(item.get("blocking")) and not bool(item.get("acknowledged"))
    )
    acknowledged = sorted(str(item["id"]) for item in findings if bool(item.get("acknowledged")))
    finding_counts = Counter(str(item.get("category") or "unknown") for item in findings)
    reconciliation_counts = Counter(str(item["classification"]) for item in reconciliation)
    boundary_counts = Counter(architectural_boundary(node) for node in nodes.values())
    cross_boundary_edge_count = sum(int(item["count"]) for item in boundary_matrix if item["cross_boundary"])
    integrity_pass = not missing_edge_evidence and not missing_invariant_sources and not unacknowledged_blocking

    return {
        "schema_version": "1.1",
        "production_node_count": len(nodes),
        "production_edge_count": len(edges),
        "boundary_counts": dict(sorted(boundary_counts.items())),
        "cross_boundary_edge_count": cross_boundary_edge_count,
        "node_metrics": metrics,
        "top_betweenness": sorted(metrics, key=lambda item: (-float(item["betweenness"]), str(item["id"])))[:25],
        "top_transitive_consumers": sorted(
            metrics,
            key=lambda item: (-int(item["transitive_consumers"]), str(item["id"])),
        )[:25],
        "boundary_matrix": boundary_matrix,
        "static_cycles": cycles,
        "semantic_reconciliation": reconciliation,
        "semantic_reconciliation_counts": dict(sorted(reconciliation_counts.items())),
        "semantic_findings": findings,
        "semantic_finding_counts": dict(sorted(finding_counts.items())),
        "integrity": {
            "missing_semantic_edge_evidence": missing_edge_evidence,
            "missing_invariant_sources": missing_invariant_sources,
            "unacknowledged_blocking_findings": unacknowledged_blocking,
            "acknowledged_semantic_findings": acknowledged,
            "semantic_finding_count": len(findings),
            "pass": integrity_pass,
        },
    }


def _print_human(report: dict[str, Any]) -> None:
    print(
        "Graph completeness: "
        f"{report['production_node_count']} production node(s), "
        f"{report['production_edge_count']} production edge(s), "
        f"{report['cross_boundary_edge_count']} cross-boundary edge(s)"
    )
    print("Semantic reconciliation:")
    for key, value in report["semantic_reconciliation_counts"].items():
        print(f"  {key}: {value}")
    print(f"Static cycles: {len(report['static_cycles'])}")
    print(f"Semantic findings: {report['integrity']['semantic_finding_count']}")
    if report["integrity"]["unacknowledged_blocking_findings"]:
        print("Unacknowledged blocking findings:")
        for finding_id in report["integrity"]["unacknowledged_blocking_findings"]:
            print(f"  {finding_id}")
    print(f"Integrity: {'PASS' if report['integrity']['pass'] else 'FAIL'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Ajenda's canonical dependency graph completeness")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    report = audit_graph(build_graph())
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    if args.as_json:
        print(rendered, end="")
    else:
        _print_human(report)
    return 0 if report["integrity"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
