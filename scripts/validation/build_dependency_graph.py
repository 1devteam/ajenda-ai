#!/usr/bin/env python3
"""Build Ajenda's canonical dependency graph from source plus semantic inventories."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_DIR = Path(__file__).resolve().parent
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

# ruff: noqa: E402

from graph_function_inventory import collect_function_graph, collect_function_test_edges
from graph_runtime_action_selection_inventory import (
    RESOLVER_PATH as ACTION_RESOLVER_PATH,
)
from graph_runtime_action_selection_inventory import (
    collect_runtime_action_selection_inventory,
)
from graph_runtime_contract_inventory import JOB_CATALOG_PATH, collect_runtime_contract_inventory
from graph_semantic_inventory import collect_semantic_inventory

OVERLAY_PATH = REPO_ROOT / "docs/contracts/dependency-graph.overlay.v1.json"
DEFAULT_OUTPUT = REPO_ROOT / "docs/architecture/dependency-graph.v1.json"
PRODUCTION_PYTHON_ROOTS = (REPO_ROOT / "backend", REPO_ROOT / "services")
GRAPH_TOOLING_PYTHON_ROOT = REPO_ROOT / "scripts" / "validation"
GRAPH_TOOLING_WORKFLOW_ROOT = REPO_ROOT / ".github" / "workflows"
INTERNAL_PYTHON_PREFIXES = ("backend", "services")
FRONTEND_IMPORT_RE = re.compile(r"(?:import|export)\s+(?:[^'\"]+?\s+from\s+)?['\"]([^'\"]+)['\"]")


@dataclass(frozen=True, slots=True)
class StaticNode:
    id: str
    type: str
    source: str


@dataclass(frozen=True, slots=True)
class StaticEdge:
    source: str
    target: str
    type: str
    evidence: str


def _python_module_for_path(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_python_import(current_module: str, *, is_package: bool, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    current_parts = current_module.split(".")
    package_parts = current_parts if is_package else current_parts[:-1]
    ascend = max(node.level - 1, 0)
    if ascend > len(package_parts):
        return None
    base = package_parts[: len(package_parts) - ascend]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _best_python_target(imported: str, modules: set[str]) -> str | None:
    if imported in modules:
        return imported
    parts = imported.split(".")
    while len(parts) > 1:
        parts.pop()
        candidate = ".".join(parts)
        if candidate in modules:
            return candidate
    return None


def _python_imports(path: Path, module: str, modules: set[str]) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    imported_modules: set[str] = set()
    is_package = path.name == "__init__.py"
    for item in ast.walk(tree):
        candidates: list[str] = []
        if isinstance(item, ast.Import):
            candidates.extend(alias.name for alias in item.names)
        elif isinstance(item, ast.ImportFrom):
            base = _resolve_python_import(module, is_package=is_package, node=item)
            if base:
                candidates.append(base)
                candidates.extend(f"{base}.{alias.name}" for alias in item.names if alias.name != "*")
        for imported in candidates:
            if not imported.startswith(INTERNAL_PYTHON_PREFIXES):
                continue
            target = _best_python_target(imported, modules)
            if target:
                imported_modules.add(target)
    return imported_modules


def _production_python_modules() -> dict[Path, str]:
    files = sorted(
        path
        for root in PRODUCTION_PYTHON_ROOTS
        if root.exists()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    return {path: _python_module_for_path(path) for path in files}


def _graph_tooling_python_modules() -> dict[Path, str]:
    if not GRAPH_TOOLING_PYTHON_ROOT.exists():
        return {}
    files = sorted(path for path in GRAPH_TOOLING_PYTHON_ROOT.rglob("*.py") if "__pycache__" not in path.parts)
    return {path: _python_module_for_path(path) for path in files}


def collect_python_graph() -> tuple[list[StaticNode], list[StaticEdge]]:
    module_by_path = _production_python_modules()
    modules = set(module_by_path.values())
    nodes = [
        StaticNode(id=f"py:{module}", type="python_module", source=str(path.relative_to(REPO_ROOT)))
        for path, module in module_by_path.items()
    ]
    edges: set[StaticEdge] = set()
    for path, module in module_by_path.items():
        for target in _python_imports(path, module, modules):
            if target != module:
                edges.add(
                    StaticEdge(
                        source=f"py:{module}",
                        target=f"py:{target}",
                        type="imports",
                        evidence=str(path.relative_to(REPO_ROOT)),
                    )
                )
    return nodes, sorted(edges, key=lambda edge: (edge.source, edge.target, edge.type))


def collect_graph_tooling_graph() -> tuple[list[StaticNode], list[StaticEdge]]:
    modules = _graph_tooling_python_modules()
    names = set(modules.values())
    nodes = [
        StaticNode(
            id=f"graph-tool:{module}",
            type="graph_tooling_module",
            source=str(path.relative_to(REPO_ROOT)),
        )
        for path, module in modules.items()
    ]
    edges: set[StaticEdge] = set()
    for path, module in modules.items():
        for target in _python_imports(path, module, names):
            if target != module:
                edges.add(
                    StaticEdge(
                        source=f"graph-tool:{module}",
                        target=f"graph-tool:{target}",
                        type="imports",
                        evidence=str(path.relative_to(REPO_ROOT)),
                    )
                )
    return nodes, sorted(edges, key=lambda edge: (edge.source, edge.target, edge.type))


def collect_graph_tooling_workflow_nodes() -> list[StaticNode]:
    if not GRAPH_TOOLING_WORKFLOW_ROOT.exists():
        return []
    return [
        StaticNode(
            id=f"graph-tool:workflow:{path.name}",
            type="graph_tooling_workflow",
            source=str(path.relative_to(REPO_ROOT)),
        )
        for path in sorted(GRAPH_TOOLING_WORKFLOW_ROOT.glob("*.y*ml"))
    ]


def collect_test_graph() -> tuple[list[StaticNode], list[StaticEdge]]:
    tests_root = REPO_ROOT / "tests"
    if not tests_root.exists():
        return [], []
    production_modules = set(_production_python_modules().values())
    nodes: list[StaticNode] = []
    edges: set[StaticEdge] = set()
    for path in sorted(path for path in tests_root.rglob("*.py") if "__pycache__" not in path.parts):
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        node_id = f"test:{rel}"
        nodes.append(StaticNode(id=node_id, type="test_module", source=rel))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        imported_modules: set[str] = set()
        for item in ast.walk(tree):
            candidates: list[str] = []
            if isinstance(item, ast.Import):
                candidates.extend(alias.name for alias in item.names)
            elif isinstance(item, ast.ImportFrom) and item.level == 0 and item.module:
                candidates.append(item.module)
                candidates.extend(f"{item.module}.{alias.name}" for alias in item.names if alias.name != "*")
            for imported in candidates:
                if not imported.startswith(INTERNAL_PYTHON_PREFIXES):
                    continue
                target = _best_python_target(imported, production_modules)
                if target:
                    imported_modules.add(target)
        for target in imported_modules:
            edges.add(StaticEdge(source=node_id, target=f"py:{target}", type="tests", evidence=rel))
    return nodes, sorted(edges, key=lambda edge: (edge.source, edge.target, edge.type))


def _frontend_source_id(path: Path) -> str:
    return "fe:" + str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def _resolve_frontend_import(source: Path, specifier: str, files: set[Path]) -> Path | None:
    if not specifier.startswith("."):
        return None
    raw = (source.parent / specifier).resolve()
    candidates = [raw, raw.with_suffix(".ts"), raw.with_suffix(".tsx"), raw / "index.ts", raw / "index.tsx"]
    return next((candidate for candidate in candidates if candidate in files), None)


def collect_frontend_graph() -> tuple[list[StaticNode], list[StaticEdge]]:
    root = REPO_ROOT / "frontend/src"
    if not root.exists():
        return [], []
    files = {path.resolve() for path in root.rglob("*") if path.suffix in {".ts", ".tsx"}}
    nodes = [
        StaticNode(id=_frontend_source_id(path), type="frontend_module", source=str(path.relative_to(REPO_ROOT)))
        for path in sorted(files)
    ]
    edges: set[StaticEdge] = set()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in FRONTEND_IMPORT_RE.finditer(text):
            target = _resolve_frontend_import(path, match.group(1), files)
            if target and target != path:
                edges.add(
                    StaticEdge(
                        source=_frontend_source_id(path),
                        target=_frontend_source_id(target),
                        type="imports",
                        evidence=str(path.relative_to(REPO_ROOT)),
                    )
                )
    return nodes, sorted(edges, key=lambda edge: (edge.source, edge.target, edge.type))


def _tarjan_scc(nodes: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for source, target in edges:
        adjacency[source].append(target)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in adjacency[node]:
            if target not in indexes:
                strongconnect(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[target])
        if lowlinks[node] != indexes[node]:
            return
        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        if len(component) > 1:
            components.append(sorted(component))

    for node in nodes:
        if node not in indexes:
            strongconnect(node)
    return sorted(components, key=lambda component: (-len(component), component))


def _rank_counts(counts: dict[str, int], node_ids: list[str]) -> list[dict[str, Any]]:
    ranked = sorted(((node, counts[node]) for node in node_ids), key=lambda item: (-item[1], item[0]))[:25]
    return [{"node": node, "count": count} for node, count in ranked if count]


def _metrics(node_ids: list[str], edges: list[dict[str, Any]]) -> dict[str, Any]:
    fan_in: dict[str, int] = defaultdict(int)
    fan_out: dict[str, int] = defaultdict(int)
    production_fan_in: dict[str, int] = defaultdict(int)
    static_pairs: list[tuple[str, str]] = []
    edge_types: Counter[str] = Counter()
    for edge in edges:
        source, target, edge_type = str(edge["from"]), str(edge["to"]), str(edge["type"])
        fan_out[source] += 1
        fan_in[target] += 1
        edge_types[edge_type] += 1
        if edge_type not in {"tests", "tests_function"}:
            production_fan_in[target] += 1
        if edge_type == "imports":
            static_pairs.append((source, target))
    return {
        "node_count": len(node_ids),
        "edge_count": len(edges),
        "edge_counts_by_type": dict(sorted(edge_types.items())),
        "top_fan_in": _rank_counts(fan_in, node_ids),
        "top_production_fan_in": _rank_counts(production_fan_in, node_ids),
        "top_fan_out": _rank_counts(fan_out, node_ids),
        "static_cycles": _tarjan_scc(node_ids, static_pairs),
    }


def build_graph() -> dict[str, Any]:
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    py_nodes, py_edges = collect_python_graph()
    tooling_nodes, tooling_edges = collect_graph_tooling_graph()
    tooling_workflow_nodes = collect_graph_tooling_workflow_nodes()
    fe_nodes, fe_edges = collect_frontend_graph()
    test_nodes, test_edges = collect_test_graph()
    function_nodes, function_edges = collect_function_graph(REPO_ROOT)
    function_test_edges = collect_function_test_edges(REPO_ROOT, function_nodes)
    semantic_inventory = collect_semantic_inventory(REPO_ROOT, overlay)
    runtime_contract_inventory = collect_runtime_contract_inventory(REPO_ROOT)
    runtime_action_selection_inventory = collect_runtime_action_selection_inventory(REPO_ROOT)

    nodes: list[dict[str, Any]] = [
        {"id": node.id, "type": node.type, "source": node.source}
        for node in [*py_nodes, *tooling_nodes, *tooling_workflow_nodes, *fe_nodes, *test_nodes]
    ]
    nodes.extend(function_nodes)
    nodes.extend(overlay.get("nodes", []))
    nodes.extend(semantic_inventory["nodes"])
    nodes.extend(runtime_contract_inventory["nodes"])
    nodes.extend(runtime_action_selection_inventory["action_nodes"])
    nodes.extend(runtime_action_selection_inventory["nodes"])

    edges: list[dict[str, Any]] = [
        {"from": edge.source, "to": edge.target, "type": edge.type, "evidence": edge.evidence}
        for edge in [*py_edges, *tooling_edges, *fe_edges, *test_edges]
    ]
    edges.extend(function_edges)
    edges.extend(function_test_edges)
    edges.extend(overlay.get("edges", []))
    edges.extend(semantic_inventory["edges"])
    edges.extend(runtime_contract_inventory["edges"])
    edges.extend(runtime_action_selection_inventory["edges"])

    node_ids_seen = [str(node["id"]) for node in nodes]
    duplicates = sorted(node_id for node_id, count in Counter(node_ids_seen).items() if count > 1)
    if duplicates:
        raise ValueError(f"Graph defines duplicate nodes: {', '.join(duplicates)}")
    known_nodes = set(node_ids_seen)
    missing = sorted(
        {
            str(endpoint)
            for edge in edges
            for endpoint in (edge.get("from"), edge.get("to"))
            if endpoint not in known_nodes
        }
    )
    if missing:
        raise ValueError(f"Graph edges reference undefined nodes: {', '.join(missing)}")

    node_ids = sorted(known_nodes)
    return {
        "schema_version": "1.4",
        "generated_from": {
            "static": [
                "backend/**/*.py",
                "services/**/*.py",
                "frontend/src/**/*.ts",
                "frontend/src/**/*.tsx",
                "tests/**/*.py",
                "alembic/versions/*.py",
            ],
            "selective_function_layer": ["backend/services/mission_composition/**/*.py"],
            "runtime_contract_catalog": str(JOB_CATALOG_PATH),
            "runtime_action_resolver": str(ACTION_RESOLVER_PATH),
            "runtime_action_implementations": "backend/services/tools/**/*.py",
            "semantic_overlay": str(OVERLAY_PATH.relative_to(REPO_ROOT)),
        },
        "nodes": sorted(nodes, key=lambda node: str(node["id"])),
        "edges": sorted(edges, key=lambda edge: (str(edge["from"]), str(edge["to"]), str(edge["type"]))),
        "invariants": overlay.get("invariants", []),
        "semantic_findings": sorted(
            [
                *semantic_inventory["findings"],
                *runtime_contract_inventory["findings"],
                *runtime_action_selection_inventory["findings"],
            ],
            key=lambda item: str(item["id"]),
        ),
        "runtime_contract_metrics": runtime_contract_inventory["metrics"],
        "runtime_action_selection_metrics": runtime_action_selection_inventory["metrics"],
        "metrics": _metrics(node_ids, edges),
    }


def _display_path(path: Path) -> str:
    """Render repository paths compactly without rejecting external artifacts."""

    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Ajenda's canonical dependency graph")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    graph = build_graph()
    rendered = json.dumps(graph, indent=2, sort_keys=True) + "\n"
    output = Path(args.output)
    if args.check:
        if not output.exists():
            print(f"FAIL: canonical graph is missing: {_display_path(output)}")
            return 1
        if output.read_text(encoding="utf-8") != rendered:
            print(f"FAIL: canonical graph is stale: {_display_path(output)}")
            return 1
        print("PASS: canonical dependency graph is current")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {_display_path(output)}")
    print(f"Nodes: {graph['metrics']['node_count']}; edges: {graph['metrics']['edge_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
