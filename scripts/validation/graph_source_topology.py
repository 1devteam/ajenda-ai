#!/usr/bin/env python3
"""Emit factual per-source topology from Ajenda's canonical dependency graph.

This script does not decide which files should move or be split. It aggregates
directly observable graph structure by source file so a receiving model can
reason about filesystem/refactor candidates without scanning the full JSON graph.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from build_dependency_graph import build_graph

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "graph-source-topology.v1.json"
TEST_EDGE_TYPES = {"tests", "tests_function"}


def _source(node: dict[str, Any]) -> str | None:
    value = node.get("source")
    if not isinstance(value, str) or not value:
        return None
    return value.replace("\\", "/")


def _namespace(source: str) -> str:
    parts = [part for part in source.split("/") if part]
    if source.startswith("backend/services/"):
        return "/".join(parts[:3]) if len(parts) >= 4 else "backend/services"
    if source.startswith("backend/"):
        return "/".join(parts[:2]) if len(parts) >= 2 else "backend"
    if source.startswith("services/"):
        return "/".join(parts[:2]) if len(parts) >= 2 else "services"
    if source.startswith("frontend/src/"):
        return "/".join(parts[:3]) if len(parts) >= 3 else "frontend/src"
    if source.startswith("scripts/validation/"):
        return "scripts/validation"
    return parts[0] if parts else "unknown"


def _file_shape(source: str) -> tuple[int | None, int | None]:
    path = REPO_ROOT / source
    if not path.is_file():
        return None, None
    try:
        raw = path.read_bytes()
    except OSError:
        return None, None
    line_count = raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)
    return len(raw), line_count


def build_source_topology(graph: dict[str, Any] | None = None) -> dict[str, Any]:
    graph = graph or build_graph()
    nodes = {str(node["id"]): node for node in graph.get("nodes", [])}

    source_nodes: dict[str, list[str]] = defaultdict(list)
    node_types: dict[str, set[str]] = defaultdict(set)
    for node_id, node in nodes.items():
        source = _source(node)
        if source is None:
            continue
        source_nodes[source].append(node_id)
        node_types[source].add(str(node.get("type") or ""))

    incoming: Counter[str] = Counter()
    outgoing: Counter[str] = Counter()
    production_incoming: Counter[str] = Counter()
    production_outgoing: Counter[str] = Counter()
    test_edges: Counter[str] = Counter()
    relations: dict[str, set[str]] = defaultdict(set)
    neighbor_sources: dict[str, set[str]] = defaultdict(set)
    neighbor_namespaces: dict[str, set[str]] = defaultdict(set)

    for edge in graph.get("edges", []):
        left = nodes.get(str(edge.get("from")))
        right = nodes.get(str(edge.get("to")))
        if left is None or right is None:
            continue
        left_source = _source(left)
        right_source = _source(right)
        edge_type = str(edge.get("type") or "")
        if left_source:
            outgoing[left_source] += 1
            relations[left_source].add(edge_type)
        if right_source:
            incoming[right_source] += 1
            relations[right_source].add(edge_type)

        is_test = edge_type in TEST_EDGE_TYPES
        if left_source:
            if is_test:
                test_edges[left_source] += 1
            else:
                production_outgoing[left_source] += 1
        if right_source:
            if is_test:
                test_edges[right_source] += 1
            else:
                production_incoming[right_source] += 1

        if left_source and right_source and left_source != right_source:
            neighbor_sources[left_source].add(right_source)
            neighbor_sources[right_source].add(left_source)
            neighbor_namespaces[left_source].add(_namespace(right_source))
            neighbor_namespaces[right_source].add(_namespace(left_source))

    rows: list[dict[str, Any]] = []
    for source in sorted(source_nodes):
        byte_count, line_count = _file_shape(source)
        rows.append(
            {
                "source": source,
                "namespace": _namespace(source),
                "bytes": byte_count,
                "lines": line_count,
                "node_count": len(source_nodes[source]),
                "node_types": sorted(node_types[source]),
                "incoming_edges": incoming[source],
                "outgoing_edges": outgoing[source],
                "incident_edges": incoming[source] + outgoing[source],
                "production_incoming_edges": production_incoming[source],
                "production_outgoing_edges": production_outgoing[source],
                "production_incident_edges": production_incoming[source] + production_outgoing[source],
                "test_incident_edges": test_edges[source],
                "relation_types": sorted(relations[source]),
                "relation_type_count": len(relations[source]),
                "neighbor_source_count": len(neighbor_sources[source]),
                "neighbor_namespace_count": len(neighbor_namespaces[source]),
                "neighbor_namespaces": sorted(neighbor_namespaces[source]),
            }
        )

    return {
        "schema_version": "1.0",
        "artifact_kind": "graft_source_topology",
        "role": "factual_source_index",
        "graph_schema_version": graph.get("schema_version"),
        "source_count": len(rows),
        "rows": rows,
    }


def _rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -int(row.get("production_incident_edges") or 0),
            -int(row.get("relation_type_count") or 0),
            -int(row.get("neighbor_source_count") or 0),
            -int(row.get("lines") or 0),
            str(row.get("source") or ""),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    artifact = build_source_topology()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    production = [
        row for row in artifact["rows"] if str(row["source"]).startswith(("backend/", "services/", "frontend/src/"))
    ]
    print(
        "Ajenda source topology: "
        f"{artifact['source_count']} source-backed files; "
        f"{len(production)} production/frontend files"
    )
    for row in _rank(production)[: max(0, args.top)]:
        print(
            "SRC "
            f"{row['source']} "
            f"prod_edges={row['production_incident_edges']} "
            f"in={row['production_incoming_edges']} "
            f"out={row['production_outgoing_edges']} "
            f"rels={row['relation_type_count']} "
            f"neighbors={row['neighbor_source_count']} "
            f"namespaces={row['neighbor_namespace_count']} "
            f"lines={row['lines']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
