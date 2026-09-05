#!/usr/bin/env python3
"""Analyze changed repository paths or selected graph nodes against Ajenda's canonical dependency graph.

Graph edges use the canonical consumer -> dependency direction. Reverse traversal
therefore answers "what can this change affect?" while forward traversal answers
"what does this component rely on?".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict, deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from build_dependency_graph import build_graph
from pr_invariant_classifier import _discover_changes, classify_risk_domains

TEST_EDGE_TYPES = frozenset({"tests", "tests_function"})
TEST_NODE_TYPE = "test_module"
SEMANTIC_NODE_TYPES = frozenset(
    {
        "runtime",
        "business_job",
        "runtime_artifact",
        "runtime_input",
        "runtime_action",
        "runtime_action_selection",
        "security_boundary",
        "external_service",
        "database_table",
        "migration",
        "network_egress_sink",
        "state_resource",
    }
)


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    return normalized[2:] if normalized.startswith("./") else normalized


def _node_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): node for node in graph["nodes"]}


def _source_index(graph: dict[str, Any]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    for node in graph["nodes"]:
        source = node.get("source")
        if isinstance(source, str) and source:
            index[_normalize_path(source)].append(str(node["id"]))
    return {source: sorted(node_ids) for source, node_ids in index.items()}


def _production_edges(graph: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for edge in graph["edges"]:
        source = str(edge["from"])
        target = str(edge["to"])
        if str(edge["type"]) in TEST_EDGE_TYPES:
            continue
        if nodes[source].get("type") == TEST_NODE_TYPE or nodes[target].get("type") == TEST_NODE_TYPE:
            continue
        edges.append(edge)
    return edges


def _adjacency(edges: Iterable[dict[str, Any]], *, reverse: bool) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        source = str(edge["from"])
        target = str(edge["to"])
        if reverse:
            source, target = target, source
        adjacency[source].add(target)
    return adjacency


def _distances(
    starts: Iterable[str],
    adjacency: dict[str, set[str]],
    *,
    max_depth: int | None,
) -> dict[str, int]:
    distance: dict[str, int] = {}
    queue: deque[str] = deque()
    for start in sorted(set(starts)):
        distance[start] = 0
        queue.append(start)
    while queue:
        current = queue.popleft()
        current_depth = distance[current]
        if max_depth is not None and current_depth >= max_depth:
            continue
        for target in sorted(adjacency.get(current, set())):
            next_depth = current_depth + 1
            known = distance.get(target)
            if known is not None and known <= next_depth:
                continue
            distance[target] = next_depth
            queue.append(target)
    return distance


def _described_nodes(
    distances: dict[str, int],
    nodes: dict[str, dict[str, Any]],
    *,
    exclude: set[str],
) -> list[dict[str, Any]]:
    described: list[dict[str, Any]] = []
    for node_id, distance in distances.items():
        if node_id in exclude:
            continue
        node = nodes[node_id]
        described.append(
            {
                "id": node_id,
                "type": node.get("type"),
                "source": node.get("source"),
                "label": node.get("label"),
                "decision_role": node.get("decision_role"),
                "distance": distance,
            }
        )
    return sorted(described, key=lambda item: (int(item["distance"]), str(item["id"])))


def _impacted_tests(
    graph: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    affected_production: set[str],
) -> list[dict[str, Any]]:
    impacted: dict[str, set[str]] = defaultdict(set)
    edge_kinds: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        edge_type = str(edge["type"])
        if edge_type not in TEST_EDGE_TYPES:
            continue
        source = str(edge["from"])
        target = str(edge["to"])
        if target in affected_production:
            impacted[source].add(target)
            edge_kinds[source].add(edge_type)
    return [
        {
            "id": test_id,
            "source": nodes[test_id].get("source"),
            "covers_affected_nodes": sorted(targets),
            "coverage_edges": sorted(edge_kinds[test_id]),
        }
        for test_id, targets in sorted(impacted.items())
    ]


def _semantic_nodes(node_ids: set[str], nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    for node_id in sorted(node_ids):
        node = nodes[node_id]
        if node.get("type") not in SEMANTIC_NODE_TYPES:
            continue
        selected.append(
            {
                "id": node_id,
                "type": node.get("type"),
                "source": node.get("source"),
                "label": node.get("label"),
            }
        )
    return selected


def _relevant_invariants(
    graph: dict[str, Any],
    source_index: dict[str, list[str]],
    *,
    changed_files: set[str],
    context_nodes: set[str],
) -> list[dict[str, Any]]:
    relevant: list[dict[str, Any]] = []
    for invariant in graph.get("invariants", []):
        matched_sources: set[str] = set()
        matched_nodes: set[str] = set()
        for raw_source in invariant.get("sources", []):
            if not isinstance(raw_source, str):
                continue
            source = _normalize_path(raw_source)
            if source in changed_files:
                matched_sources.add(source)
            for node_id in source_index.get(source, []):
                if node_id in context_nodes:
                    matched_sources.add(source)
                    matched_nodes.add(node_id)
        for node_id in invariant.get("applies_to", []):
            if isinstance(node_id, str) and node_id in context_nodes:
                matched_nodes.add(node_id)
        if not matched_sources and not matched_nodes:
            continue
        relevant.append(
            {
                "id": invariant.get("id"),
                "status": invariant.get("status"),
                "rule": invariant.get("rule"),
                "matched_sources": sorted(matched_sources),
                "matched_nodes": sorted(matched_nodes),
            }
        )
    return sorted(relevant, key=lambda item: str(item["id"]))


def _analyze_starts(
    graph: dict[str, Any],
    *,
    changed_files: list[str],
    changed_node_ids: list[str],
    unmapped_changed_files: list[str],
    max_depth: int | None,
) -> dict[str, Any]:
    nodes = _node_map(graph)
    source_index = _source_index(graph)
    changed_nodes = [nodes[node_id] for node_id in changed_node_ids]
    changed_production = {node_id for node_id in changed_node_ids if nodes[node_id].get("type") != TEST_NODE_TYPE}

    production_edges = _production_edges(graph, nodes)
    forward = _adjacency(production_edges, reverse=False)
    reverse = _adjacency(production_edges, reverse=True)
    upstream_distances = _distances(changed_production, reverse, max_depth=max_depth)
    downstream_distances = _distances(changed_production, forward, max_depth=max_depth)
    upstream_ids = set(upstream_distances) - changed_production
    downstream_ids = set(downstream_distances) - changed_production
    affected_production = changed_production | upstream_ids
    context_nodes = affected_production | downstream_ids
    impacted_tests = _impacted_tests(graph, nodes, affected_production)

    risk_profiles = classify_risk_domains(changed_files)
    invariants = _relevant_invariants(
        graph,
        source_index,
        changed_files=set(changed_files),
        context_nodes=context_nodes,
    )
    affected_semantic = _semantic_nodes(affected_production, nodes)
    dependency_semantic = _semantic_nodes(downstream_ids, nodes)

    return {
        "schema_version": "1.2",
        "changed_files": changed_files,
        "changed_nodes": [
            {
                "id": str(node["id"]),
                "type": node.get("type"),
                "source": node.get("source"),
                "label": node.get("label"),
                "decision_role": node.get("decision_role"),
            }
            for node in changed_nodes
        ],
        "unmapped_changed_files": unmapped_changed_files,
        "upstream_consumers": _described_nodes(upstream_distances, nodes, exclude=changed_production),
        "downstream_dependencies": _described_nodes(downstream_distances, nodes, exclude=changed_production),
        "impacted_tests": impacted_tests,
        "affected_semantic_nodes": affected_semantic,
        "dependency_semantic_nodes": dependency_semantic,
        "relevant_invariants": invariants,
        "risk_domains": [
            {
                "id": profile.id,
                "title": profile.title,
                "review": list(profile.review),
            }
            for profile in risk_profiles
        ],
        "metrics": {
            "changed_file_count": len(changed_files),
            "changed_node_count": len(changed_node_ids),
            "unmapped_changed_file_count": len(unmapped_changed_files),
            "upstream_consumer_count": len(upstream_ids),
            "downstream_dependency_count": len(downstream_ids),
            "impacted_test_count": len(impacted_tests),
            "affected_semantic_node_count": len(affected_semantic),
            "dependency_semantic_node_count": len(dependency_semantic),
            "relevant_invariant_count": len(invariants),
            "risk_domain_count": len(risk_profiles),
        },
    }


def analyze_impact(
    graph: dict[str, Any],
    changed_files: Iterable[str],
    *,
    max_depth: int | None = None,
) -> dict[str, Any]:
    changed = sorted({_normalize_path(path) for path in changed_files})
    changed_set = set(changed)
    source_index = _source_index(graph)
    changed_node_ids = sorted({node_id for path in changed for node_id in source_index.get(path, [])})
    mapped_sources = {path for path in changed if path in source_index}
    unmapped = sorted(changed_set - mapped_sources)
    return _analyze_starts(
        graph,
        changed_files=changed,
        changed_node_ids=changed_node_ids,
        unmapped_changed_files=unmapped,
        max_depth=max_depth,
    )


def analyze_node_impact(
    graph: dict[str, Any],
    changed_nodes: Iterable[str],
    *,
    max_depth: int | None = None,
) -> dict[str, Any]:
    nodes = _node_map(graph)
    requested = sorted(set(changed_nodes))
    missing = sorted(node_id for node_id in requested if node_id not in nodes)
    if missing:
        raise ValueError(f"Unknown graph node(s): {', '.join(missing)}")
    changed_files = sorted(
        {
            _normalize_path(str(nodes[node_id]["source"]))
            for node_id in requested
            if isinstance(nodes[node_id].get("source"), str) and nodes[node_id].get("source")
        }
    )
    return _analyze_starts(
        graph,
        changed_files=changed_files,
        changed_node_ids=requested,
        unmapped_changed_files=[],
        max_depth=max_depth,
    )


def _print_human(report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    print(
        "Impact: "
        f"{metrics['changed_node_count']} changed graph node(s), "
        f"{metrics['upstream_consumer_count']} upstream consumer(s), "
        f"{metrics['downstream_dependency_count']} downstream prerequisite(s), "
        f"{metrics['impacted_test_count']} impacted test(s)"
    )
    print(
        "Architecture: "
        f"{metrics['affected_semantic_node_count']} affected semantic node(s), "
        f"{metrics['dependency_semantic_node_count']} semantic prerequisite(s), "
        f"{metrics['relevant_invariant_count']} relevant invariant(s)"
    )
    for node in report["changed_nodes"]:
        role = f" [{node['decision_role']}]" if node.get("decision_role") else ""
        print(f"CHANGED: {node['id']}{role} ({node.get('source') or node.get('label')})")
    for path in report["unmapped_changed_files"]:
        print(f"UNMAPPED: {path}")
    for invariant in report["relevant_invariants"]:
        print(f"INVARIANT: {invariant['id']} [{invariant['status']}]")
    for profile in report["risk_domains"]:
        print(f"RISK: {profile['id']} — {profile['title']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute Ajenda graph-aware change impact.")
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--changed-node", action="append", default=[])
    parser.add_argument("--max-depth", type=int)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--output")
    args = parser.parse_args()
    if bool(args.base_ref) != bool(args.head_ref):
        parser.error("--base-ref and --head-ref must be supplied together")
    if args.max_depth is not None and args.max_depth < 0:
        parser.error("--max-depth must be zero or greater")
    if args.changed_node and (args.changed_file or args.base_ref or args.head_ref):
        parser.error("--changed-node cannot be combined with changed-file or ref-based discovery")

    graph = build_graph()
    try:
        if args.changed_node:
            report = analyze_node_impact(graph, args.changed_node, max_depth=args.max_depth)
        else:
            if args.changed_file:
                changed = sorted(set(args.changed_file))
            else:
                try:
                    changed, _ = _discover_changes(args.base_ref, args.head_ref)
                except RuntimeError as exc:
                    print(f"FAIL: unable to determine changed files: {exc}")
                    return 1
            report = analyze_impact(graph, changed, max_depth=args.max_depth)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1

    graph_bytes = json.dumps(graph, sort_keys=True, separators=(",", ":")).encode("utf-8")
    report["graph_sha256"] = hashlib.sha256(graph_bytes).hexdigest()
    report["comparison"] = {
        "base_ref": args.base_ref,
        "head_ref": args.head_ref,
        "mode": "git-range" if args.base_ref and args.head_ref else "explicit-or-working-tree",
        "delta": {
            "changed_files": report["metrics"]["changed_file_count"],
            "changed_nodes": report["metrics"]["changed_node_count"],
            "unmapped_changed_files": report["metrics"]["unmapped_changed_file_count"],
            "impacted_tests": report["metrics"]["impacted_test_count"],
            "relevant_invariants": report["metrics"]["relevant_invariant_count"],
        },
    }

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    if args.as_json:
        print(rendered, end="")
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
