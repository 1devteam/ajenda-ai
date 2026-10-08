#!/usr/bin/env python3
"""Compare Ajenda's judged target filesystem against the canonical/federated GRAFT evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_DIR = Path(__file__).resolve().parent
for candidate in (REPO_ROOT, VALIDATION_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from build_dependency_graph import build_graph  # noqa: E402
from graft_capability_registry import build_machine_registry  # noqa: E402
from graft_plus_graft1st_reconciliation_check import validate_conformance  # noqa: E402
from graph_completeness_audit import audit_graph  # noqa: E402
from graph_filesystem_projection import build_projection  # noqa: E402
from graph_runtime_contract_consumption import adjudicate_runtime_contracts_with_consumption  # noqa: E402

SERVICE_ROOT = "backend/services/"


def _sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _source(node: dict[str, Any]) -> str:
    return str(node.get("source") or "").replace("\\", "/")


def _current_boundary(source: str) -> str:
    if not source.startswith(SERVICE_ROOT):
        parts = source.split("/")
        return ":".join(parts[:2]) if len(parts) >= 2 else source
    rel = source[len(SERVICE_ROOT) :]
    parts = [item for item in rel.split("/") if item]
    if len(parts) >= 2:
        return f"svc:{parts[0]}"
    return "svc:root"


def _load_target(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("k") != "ajenda_target_filesystem":
        raise ValueError("invalid Ajenda target filesystem artifact")
    return value


def _flat_service_files() -> set[str]:
    return {
        path.name
        for path in (REPO_ROOT / SERVICE_ROOT).glob("*.py")
        if path.name != "__init__.py"
    }


def _target_rows(target: dict[str, Any]) -> dict[str, tuple[str, str, int]]:
    rows: dict[str, tuple[str, str, int]] = {}
    for item in target.get("m", []):
        if not isinstance(item, list) or len(item) != 4:
            raise ValueError("target mapping rows must be [source,target_package,target_name,role_id]")
        source, package, name, role_id = item
        if not all(isinstance(value, str) for value in (source, package, name)) or not isinstance(role_id, int):
            raise ValueError("target mapping row has invalid types")
        if source in rows:
            raise ValueError(f"duplicate target mapping: {source}")
        rows[source] = (package, name, role_id)
    return rows


def _target_boundary(source: str, rows: dict[str, tuple[str, str, int]]) -> str:
    if not source.startswith(SERVICE_ROOT):
        return _current_boundary(source)
    rel = source[len(SERVICE_ROOT) :]
    parts = [item for item in rel.split("/") if item]
    if len(parts) >= 2:
        return f"svc:{parts[0]}"
    row = rows.get(rel)
    if row is None:
        return "svc:root:unmapped"
    package = row[0]
    return "svc:root" if package == "__root__" else f"svc:{package}"


def _source_relations(graph: dict[str, Any]) -> list[tuple[str, str, str]]:
    nodes = {
        str(node["id"]): node
        for node in graph.get("nodes", [])
        if str(node.get("type")) != "test_module" and _source(node)
    }
    relations: set[tuple[str, str, str]] = set()
    for edge in graph.get("edges", []):
        if str(edge.get("type")) == "tests":
            continue
        source_node = nodes.get(str(edge.get("from")))
        target_node = nodes.get(str(edge.get("to")))
        if source_node is None or target_node is None:
            continue
        left, right = _source(source_node), _source(target_node)
        if not left or not right or left == right:
            continue
        relations.add((left, right, str(edge.get("type") or "")))
    return sorted(relations)


def _cycle_sources(graph: dict[str, Any]) -> list[set[str]]:
    node_source = {str(node["id"]): _source(node) for node in graph.get("nodes", [])}
    result: list[set[str]] = []
    for cycle in graph.get("metrics", {}).get("static_cycles", []):
        sources = {node_source.get(str(node_id), "") for node_id in cycle}
        sources.discard("")
        if sources:
            result.append(sources)
    return result


def _package_members(
    *,
    rows: dict[str, tuple[str, str, int]],
    sources: set[str],
) -> dict[str, set[str]]:
    members: dict[str, set[str]] = defaultdict(set)
    for source in sources:
        if source.startswith(SERVICE_ROOT):
            rel = source[len(SERVICE_ROOT) :]
            parts = [item for item in rel.split("/") if item]
            if len(parts) >= 2:
                members[parts[0]].add(source)
    for name, (package, _target_name, _role_id) in rows.items():
        if package != "__root__":
            members[package].add(f"{SERVICE_ROOT}{name}")
    return members


def _metric_by_source(graph: dict[str, Any], audit: dict[str, Any]) -> dict[str, dict[str, float]]:
    node_source = {str(node["id"]): _source(node) for node in graph.get("nodes", [])}
    result: dict[str, dict[str, float]] = defaultdict(
        lambda: {"tc": 0.0, "td": 0.0, "b": 0.0, "dc": 0.0, "dd": 0.0}
    )
    for item in audit.get("node_metrics", []):
        source = node_source.get(str(item.get("id")), "")
        if not source:
            continue
        row = result[source]
        row["tc"] = max(row["tc"], float(item.get("transitive_consumers") or 0))
        row["td"] = max(row["td"], float(item.get("transitive_dependencies") or 0))
        row["b"] = max(row["b"], float(item.get("betweenness") or 0))
        row["dc"] += float(item.get("direct_consumers") or 0)
        row["dd"] += float(item.get("direct_dependencies") or 0)
    return result


def compare(target: dict[str, Any]) -> dict[str, Any]:
    rows = _target_rows(target)
    actual_flat = _flat_service_files()
    mapped_flat = set(rows)
    if actual_flat != mapped_flat:
        raise ValueError(
            "target map does not exactly cover flat services: "
            + json.dumps(
                {
                    "missing": sorted(actual_flat - mapped_flat),
                    "stale": sorted(mapped_flat - actual_flat),
                },
                sort_keys=True,
            )
        )

    graph = build_graph()
    audit = audit_graph(graph)
    projection = build_projection(graph=graph, audit=audit)
    registry = build_machine_registry()
    runtime = adjudicate_runtime_contracts_with_consumption(graph)
    graft1st = validate_conformance()

    sources = {_source(node) for node in graph.get("nodes", []) if _source(node)}
    relations = _source_relations(graph)
    cycle_sets = _cycle_sources(graph)
    metric = _metric_by_source(graph, audit)
    members = _package_members(rows=rows, sources=sources)

    current_cross = 0
    target_cross = 0
    internalized = 0
    externalized = 0
    relation_delta: Counter[tuple[str, str]] = Counter()
    for left, right, _edge_type in relations:
        cb_left, cb_right = _current_boundary(left), _current_boundary(right)
        tb_left, tb_right = _target_boundary(left, rows), _target_boundary(right, rows)
        before = cb_left != cb_right
        after = tb_left != tb_right
        current_cross += int(before)
        target_cross += int(after)
        internalized += int(before and not after)
        externalized += int(not before and after)
        if before != after:
            relation_delta[(cb_left + ">" + cb_right, tb_left + ">" + tb_right)] += 1

    projection_by_source = {
        str(item.get("source")): item
        for item in projection.get("candidate_files", [])
        if isinstance(item.get("source"), str)
    }

    package_names = sorted(members)
    package_rows: list[dict[str, Any]] = []
    outliers: list[dict[str, Any]] = []
    for package in package_names:
        member_set = members[package]
        direct_internal = 0
        inbound = 0
        outbound = 0
        connected: set[str] = set()
        edge_types: Counter[str] = Counter()
        for left, right, edge_type in relations:
            left_in, right_in = left in member_set, right in member_set
            if left_in and right_in:
                direct_internal += 1
                connected.update((left, right))
                edge_types[edge_type] += 1
            elif left_in:
                outbound += 1
            elif right_in:
                inbound += 1

        touched_cycles = sum(1 for cycle in cycle_sets if cycle & member_set)
        rows_in_package = sorted(source for source in member_set if source.startswith(SERVICE_ROOT))
        package_rows.append(
            {
                "p": package,
                "n": len(member_set),
                "k": direct_internal,
                "in": inbound,
                "out": outbound,
                "pc": len(connected),
                "cy": touched_cycles,
                "et": dict(sorted(edge_types.items())),
            }
        )

        for source in rows_in_package:
            if source not in projection_by_source:
                continue
            item = projection_by_source[source]
            affinity = [
                [str(row.get("package")), int(row.get("score") or 0), int(row.get("edge_count") or 0)]
                for row in item.get("package_affinity", [])[:3]
            ]
            peer_relations = sum(
                1
                for left, right, _edge_type in relations
                if (left == source and right in member_set) or (right == source and left in member_set)
            )
            if peer_relations == 0 or (affinity and affinity[0][1] >= 12 and affinity[0][0] != package):
                outliers.append(
                    {
                        "s": source,
                        "p": package,
                        "pr": peer_relations,
                        "af": affinity,
                        "m": metric.get(source, {}),
                    }
                )

    protected = target.get("protected", {})
    protected_rows: list[dict[str, Any]] = []
    for name, config in sorted(protected.items()):
        paths = [str(path) for path in config.get("paths", [])]
        protected_rows.append(
            {
                "id": name,
                "ok": all(path in sources for path in paths),
                "missing": sorted(path for path in paths if path not in sources),
                "routine_absorb": bool(config.get("absorb_into_routine_graft")),
                "frontier_absorb": bool(config.get("absorb_into_frontier")),
            }
        )

    runtime_witness_sources = sorted(
        {
            source
            for result in runtime.get("results", [])
            for source in result.get("witness_sources", [])
            if isinstance(source, str)
        }
    )
    target_move_sources = {f"{SERVICE_ROOT}{name}" for name, (package, _name, _role) in rows.items() if package != "__root__"}
    runtime_touched = sorted(target_move_sources & set(runtime_witness_sources))

    artifact = {
        "v": 1,
        "k": "ajenda_target_filesystem_graft_comparison",
        "g": _sha(graph),
        "tr": _sha(target),
        "gr": registry["h"],
        "i": bool(audit.get("integrity", {}).get("pass")),
        "base": {
            "n": int(audit.get("production_node_count", 0)),
            "e": int(audit.get("production_edge_count", 0)),
            "c": len(cycle_sets),
            "x": current_cross,
        },
        "target": {
            "x": target_cross,
            "i": internalized,
            "e": externalized,
            "p": package_rows,
        },
        "delta": [
            [before, after, count]
            for (before, after), count in sorted(relation_delta.items(), key=lambda item: (-item[1], item[0]))
        ],
        "out": sorted(outliers, key=lambda item: (-float(item.get("m", {}).get("tc", 0)), item["s"])),
        "pf": protected_rows,
        "rt": runtime_touched,
        "g1": {
            "s": graft1st.get("status"),
            "n": int(graft1st.get("node_count", 0)),
        },
        "auth": {"runtime": False, "source_mutation": False, "promotion": False},
    }
    artifact["h"] = _sha(artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    artifact = compare(_load_target(args.target))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    print(
        "GRAFT target comparison "
        f"nodes={artifact['base']['n']} edges={artifact['base']['e']} cycles={artifact['base']['c']} "
        f"cross={artifact['base']['x']}->{artifact['target']['x']} "
        f"internalized={artifact['target']['i']} externalized={artifact['target']['e']} "
        f"outliers={len(artifact['out'])} runtime_touched={len(artifact['rt'])}"
    )
    for row in artifact["target"]["p"]:
        print(
            f"PKG {row['p']} n={row['n']} internal={row['k']} inbound={row['in']} "
            f"outbound={row['out']} peer_connected={row['pc']} cycles={row['cy']}"
        )
    for row in artifact["out"][:20]:
        print(f"OUT {row['s']} -> {row['p']} peer={row['pr']} affinity={row['af']}")
    for row in artifact["pf"]:
        print(f"PROTECTED {row['id']} ok={row['ok']} missing={len(row['missing'])}")
    return 0 if artifact["i"] and all(row["ok"] for row in artifact["pf"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
