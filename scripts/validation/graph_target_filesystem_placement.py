#!/usr/bin/env python3
"""Build a machine-native placement artifact for an architect-authored filesystem target."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_DIR = Path(__file__).resolve().parent
for candidate in (REPO_ROOT, VALIDATION_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from build_dependency_graph import build_graph  # noqa: E402
from graft_capability_registry import build_machine_registry  # noqa: E402
from graft_drift_controls import validate_graph_authority_boundaries  # noqa: E402
from graft_plus_graft1st_reconciliation_check import IMPLEMENTATION_PROOFS, validate_conformance  # noqa: E402
from graph_architecture_decision import build_decision_manifest  # noqa: E402
from graph_completeness_audit import audit_graph  # noqa: E402
from graph_deployment_inventory import collect_deployment_inventory  # noqa: E402
from graph_impact_analysis import analyze_impact  # noqa: E402
from graph_proof_selection import select_proofs  # noqa: E402
from graph_runtime_action_selection_adjudication import adjudicate_runtime_action_selection  # noqa: E402
from graph_runtime_contract_consumption import adjudicate_runtime_contracts_with_consumption  # noqa: E402
from graph_runtime_support_inventory import collect_runtime_support_inventory  # noqa: E402

from backend.services.graft_artifact_lifecycle import GRAFT_ARTIFACT_LIFECYCLE_CONTRACTS  # noqa: E402
from backend.services.runtime_admission_coverage import RUNTIME_ADMISSION_COVERAGE  # noqa: E402

SERVICE_ROOT = "backend/services/"
TEXT_REFERENCE_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sh",
    ".tsx",
    ".ts",
}


def _sha(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_target(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("k") != "ajenda_target_filesystem" or value.get("v") != 2:
        raise ValueError("target must be ajenda_target_filesystem v2")
    return value


def _rows(target: dict[str, Any]) -> list[tuple[str, str, int, int]]:
    rows: list[tuple[str, str, int, int]] = []
    seen: set[str] = set()
    for raw in target.get("m", []):
        if not isinstance(raw, list) or len(raw) != 4:
            raise ValueError("target row must be [source_name,destination,boundary_id,role_id]")
        source_name, destination, boundary_id, role_id = raw
        if not isinstance(source_name, str) or not isinstance(destination, str):
            raise ValueError("target source and destination must be strings")
        if not isinstance(boundary_id, int) or not isinstance(role_id, int):
            raise ValueError("target boundary and role ids must be integers")
        if source_name in seen:
            raise ValueError(f"duplicate target source: {source_name}")
        seen.add(source_name)
        rows.append((source_name, destination, boundary_id, role_id))
    return rows


def _flat_service_files() -> set[str]:
    return {path.name for path in (REPO_ROOT / SERVICE_ROOT).glob("*.py") if path.name != "__init__.py"}


def _module(path: str) -> str | None:
    if not path.endswith(".py"):
        return None
    return path[:-3].replace("/", ".")


def _graph_source_index(graph: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for node in graph.get("nodes", []):
        source = node.get("source")
        if isinstance(source, str) and source:
            result[source].append(str(node["id"]))
    return {source: sorted(ids) for source, ids in result.items()}


def _direct_source_edges(
    graph: dict[str, Any],
    *,
    moved_sources: set[str],
) -> list[tuple[str, str, str]]:
    nodes = {str(node["id"]): node for node in graph.get("nodes", [])}
    rows: set[tuple[str, str, str]] = set()
    for edge in graph.get("edges", []):
        if str(edge.get("type")) == "tests":
            continue
        left = nodes.get(str(edge.get("from")))
        right = nodes.get(str(edge.get("to")))
        if left is None or right is None:
            continue
        source = left.get("source")
        target = right.get("source")
        if not isinstance(source, str) or not isinstance(target, str) or source == target:
            continue
        if source in moved_sources or target in moved_sources:
            rows.add((source, target, str(edge.get("type") or "")))
    return sorted(rows)


def _test_links(graph: dict[str, Any], *, moved_node_ids: set[str]) -> list[tuple[str, str]]:
    nodes = {str(node["id"]): node for node in graph.get("nodes", [])}
    rows: set[tuple[str, str]] = set()
    for edge in graph.get("edges", []):
        if str(edge.get("type")) != "tests" or str(edge.get("to")) not in moved_node_ids:
            continue
        source_node = nodes.get(str(edge.get("from")))
        target_node = nodes.get(str(edge.get("to")))
        if source_node is None or target_node is None:
            continue
        test_source = source_node.get("source")
        production_source = target_node.get("source")
        if isinstance(test_source, str) and isinstance(production_source, str):
            rows.add((test_source, production_source))
    return sorted(rows)


def _text_reference_index(
    module_rewrites: list[list[str]],
    move_rows: list[tuple[str, str, int, int]],
) -> tuple[list[str], list[str], list[list[int]]]:
    patterns: list[str] = []
    for old_module, _new_module in module_rewrites:
        patterns.append(old_module)
    for source, _destination, _boundary_id, _role_id in move_rows:
        patterns.append(source)
    patterns = sorted(set(patterns))
    pattern_id = {value: index for index, value in enumerate(patterns)}

    refs: list[list[int]] = []
    reference_files: set[str] = set()
    raw_rows: list[tuple[str, int]] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_REFERENCE_SUFFIXES:
            continue
        if ".git" in path.parts:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in patterns:
            if pattern in text:
                reference_files.add(rel)
                raw_rows.append((rel, pattern_id[pattern]))

    files = sorted(reference_files)
    file_id = {value: index for index, value in enumerate(files)}
    refs = sorted({(file_id[path], pid) for path, pid in raw_rows})
    return files, patterns, [[fid, pid] for fid, pid in refs]


def _package_scaffolding(move_rows: list[tuple[str, str, int, int]]) -> list[str]:
    required: set[str] = set()
    for _source, destination, _boundary_id, _role_id in move_rows:
        parent = (REPO_ROOT / destination).parent
        while parent != REPO_ROOT and parent.name not in {"backend", "tests"}:
            required.add(parent.relative_to(REPO_ROOT).as_posix())
            parent = parent.parent
    return sorted(
        directory
        for directory in required
        if not (REPO_ROOT / directory / "__init__.py").is_file()
    )


def _runtime_rows(report: dict[str, Any], moved_sources: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in report.get("results", []):
        witnesses = sorted(
            source
            for source in item.get("witness_sources", [])
            if isinstance(source, str) and source in moved_sources
        )
        if not witnesses:
            continue
        selection = item.get("action_selection")
        rows.append(
            {
                "id": item.get("finding_id"),
                "r": item.get("result"),
                "j": item.get("job"),
                "a": item.get("action"),
                "ar": item.get("artifact"),
                "w": witnesses,
                "sel": selection.get("state") if isinstance(selection, dict) else None,
                "role": selection.get("normal_role") if isinstance(selection, dict) else None,
            }
        )
    return sorted(rows, key=lambda item: str(item.get("id")))


def _governance_path_refs(moved_sources: set[str]) -> dict[str, list[dict[str, Any]]]:
    lifecycle = [
        {
            "artifact": contract.artifact_type,
            "source": contract.producer,
            "owner": contract.owner,
        }
        for contract in GRAFT_ARTIFACT_LIFECYCLE_CONTRACTS
        if contract.producer in moved_sources
    ]
    admission = [
        {
            "id": boundary.boundary_id,
            "source": boundary.source_path,
            "owner": boundary.authority_owner,
            "scope": boundary.mutation_scope,
        }
        for boundary in RUNTIME_ADMISSION_COVERAGE
        if boundary.source_path in moved_sources
    ]
    graft1st: list[dict[str, Any]] = []
    for node_key, proofs in IMPLEMENTATION_PROOFS.items():
        for proof in proofs:
            if proof.path in moved_sources:
                graft1st.append({"node": node_key, "source": proof.path})
    return {
        "lifecycle": sorted(lifecycle, key=lambda item: str(item["artifact"])),
        "admission": sorted(admission, key=lambda item: str(item["id"])),
        "graft1st": sorted(graft1st, key=lambda item: (str(item["node"]), str(item["source"]))),
    }


def _graph_path_refs(graph: dict[str, Any], moved_sources: set[str]) -> dict[str, list[Any]]:
    invariants = [
        {
            "id": invariant.get("id"),
            "sources": sorted(source for source in invariant.get("sources", []) if source in moved_sources),
        }
        for invariant in graph.get("invariants", [])
        if any(source in moved_sources for source in invariant.get("sources", []))
    ]
    evidence = sorted(
        {
            str(edge["evidence"])
            for edge in graph.get("edges", [])
            if isinstance(edge.get("evidence"), str) and edge.get("evidence") in moved_sources
        }
    )
    findings = [
        str(item.get("id"))
        for item in graph.get("semantic_findings", [])
        if any(source in moved_sources for source in item.get("evidence", []))
    ]
    return {
        "invariants": sorted(invariants, key=lambda item: str(item["id"])),
        "edge_evidence": evidence,
        "semantic_findings": sorted(findings),
    }


def build_placement(
    target: dict[str, Any],
    *,
    graph: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = _rows(target)
    current_flat = _flat_service_files()
    mapped_flat = {source_name for source_name, _destination, _boundary_id, _role_id in rows}
    if current_flat != mapped_flat:
        raise ValueError(
            "target does not exactly cover flat services: "
            + json.dumps(
                {
                    "missing": sorted(current_flat - mapped_flat),
                    "stale": sorted(mapped_flat - current_flat),
                },
                sort_keys=True,
            )
        )

    move_rows = [
        (f"{SERVICE_ROOT}{source_name}", destination, boundary_id, role_id)
        for source_name, destination, boundary_id, role_id in rows
        if f"{SERVICE_ROOT}{source_name}" != destination
    ]
    moved_sources = {source for source, _destination, _boundary_id, _role_id in move_rows}

    graph = graph or build_graph()
    audit = audit or audit_graph(graph)
    source_index = _graph_source_index(graph)
    moved_node_ids = {node_id for source in moved_sources for node_id in source_index.get(source, [])}

    impact = analyze_impact(graph, sorted(moved_sources))
    proof = select_proofs(impact)
    decision = build_decision_manifest(impact, proof, audit)

    runtime_consumption = adjudicate_runtime_contracts_with_consumption(graph)
    runtime_selection = adjudicate_runtime_action_selection(graph)
    runtime_support = collect_runtime_support_inventory(REPO_ROOT)
    deployment = collect_deployment_inventory(REPO_ROOT)
    graft1st = validate_conformance()
    registry = build_machine_registry()
    authority_errors = validate_graph_authority_boundaries()

    direct_edges = _direct_source_edges(graph, moved_sources=moved_sources)
    test_links = _test_links(graph, moved_node_ids=moved_node_ids)
    file_values = sorted(
        set(moved_sources)
        | {destination for _source, destination, _boundary_id, _role_id in move_rows}
        | set(impact.get("changed_files", []))
        | {left for left, _right, _edge_type in direct_edges}
        | {right for _left, right, _edge_type in direct_edges}
        | {test for test, _source in test_links}
        | {source for _test, source in test_links}
    )
    file_id = {value: index for index, value in enumerate(file_values)}
    edge_types = sorted({edge_type for _left, _right, edge_type in direct_edges})
    edge_type_id = {value: index for index, value in enumerate(edge_types)}

    move_table = [
        [file_id[source], file_id[destination], boundary_id, role_id]
        for source, destination, boundary_id, role_id in move_rows
    ]
    module_rewrites = [
        [old, new]
        for source, destination, _boundary_id, _role_id in move_rows
        if (old := _module(source)) is not None
        and (new := _module(destination)) is not None
        and old != new
    ]
    edge_table = [
        [file_id[left], file_id[right], edge_type_id[edge_type]]
        for left, right, edge_type in direct_edges
    ]
    reference_files, reference_patterns, reference_rows = _text_reference_index(module_rewrites, move_rows)
    scaffolding = _package_scaffolding(move_rows)
    test_table = [
        [file_id[test], file_id[source]]
        for test, source in test_links
    ]

    runtime_rows = _runtime_rows(runtime_selection, moved_sources)
    governance = _governance_path_refs(moved_sources)
    graph_refs = _graph_path_refs(graph, moved_sources)

    protected_rows = []
    for key, config in sorted(target.get("protected", {}).items()):
        paths = [str(path) for path in config.get("paths", [])]
        protected_rows.append(
            {
                "id": key,
                "ok": all(path in source_index for path in paths),
                "missing": sorted(path for path in paths if path not in source_index),
                "routine_graft": bool(config.get("routine_graft")),
                "frontier": bool(config.get("frontier")),
            }
        )

    artifact: dict[str, Any] = {
        "v": 1,
        "k": "graft_target_filesystem_placement",
        "g": _sha(graph),
        "tr": _sha(target),
        "gr": registry["h"],
        "f": file_values,
        "et": edge_types,
        "mv": move_table,
        "mr": module_rewrites,
        "de": edge_table,
        "tt": test_table,
        "rf": reference_files,
        "rp": reference_patterns,
        "rr": reference_rows,
        "sc": scaffolding,
        "impact": {
            "n": [str(item.get("id")) for item in impact.get("changed_nodes", [])],
            "up": [str(item.get("id")) for item in impact.get("upstream_consumers", [])],
            "down": [str(item.get("id")) for item in impact.get("downstream_dependencies", [])],
            "tests": list(impact.get("impacted_tests", [])),
            "sem": [str(item.get("id")) for item in impact.get("affected_semantic_nodes", [])],
            "inv": [str(item.get("id")) for item in impact.get("relevant_invariants", [])],
            "risk": [str(item.get("id")) for item in impact.get("risk_domains", [])],
        },
        "proof": {
            "tests": list(proof.get("required_tests", [])),
            "gates": list(proof.get("required_gates", [])),
            "review": list(proof.get("review_gates", [])),
            "bundles": [str(item.get("id")) for item in proof.get("selected_bundles", [])],
            "manual": len(proof.get("manual_review", [])),
        },
        "decision": {
            "d": decision.get("decision", {}).get("architecture_disposition"),
            "full": bool(decision.get("decision", {}).get("full_ci_required")),
            "block": len(decision.get("decision", {}).get("blocking_reasons", [])),
            "review": len(decision.get("decision", {}).get("review_reasons", [])),
            "warn": len(decision.get("decision", {}).get("warnings", [])),
        },
        "runtime": {
            "rows": runtime_rows,
            "consumption": dict(runtime_consumption.get("metrics", {})),
            "selection": dict(runtime_selection.get("metrics", {})),
        },
        "support": {
            "runtime": dict(runtime_support.get("metrics", {})),
            "deployment": dict(deployment.get("metrics", {})),
            "runtime_findings": [str(item.get("id")) for item in runtime_support.get("findings", [])],
            "deployment_findings": [str(item.get("id")) for item in deployment.get("findings", [])],
            "deployment_unknowns": [str(item.get("id")) for item in deployment.get("unknowns", [])],
        },
        "refs": {
            "gov": governance,
            "graph": graph_refs,
        },
        "g1": {
            "s": graft1st.get("status"),
            "n": int(graft1st.get("node_count", 0)),
            "e": list(graft1st.get("errors", [])),
        },
        "auth": {
            "graph_errors": authority_errors,
            "runtime": False,
            "source_mutation": False,
            "promotion": False,
        },
        "pf": protected_rows,
    }
    artifact["h"] = _sha(artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--completeness-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    graph = json.loads(args.graph.read_text(encoding="utf-8")) if args.graph else None
    audit = (
        json.loads(args.completeness_report.read_text(encoding="utf-8"))
        if args.completeness_report
        else None
    )
    if audit is not None and graph is None:
        raise ValueError("--completeness-report requires --graph")
    artifact = build_placement(_load_target(args.target), graph=graph, audit=audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        "GRAFT placement "
        f"moves={len(artifact['mv'])} "
        f"direct_edges={len(artifact['de'])} "
        f"tests={len(artifact['impact']['tests'])} "
        f"runtime_rows={len(artifact['runtime']['rows'])} "
        f"graft1st={artifact['g1']['s']} "
        f"decision={artifact['decision']['d']}"
    )

    protected_ok = all(row["ok"] and not row["routine_graft"] and not row["frontier"] for row in artifact["pf"])
    clean = (
        protected_ok
        and artifact["g1"]["s"] == "passed"
        and not artifact["auth"]["graph_errors"]
        and not artifact["support"]["runtime_findings"]
        and not artifact["support"]["deployment_findings"]
    )
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
