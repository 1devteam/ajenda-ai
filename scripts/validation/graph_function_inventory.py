"""Selective function-level graph inventory for Ajenda intelligence-critical code.

The canonical graph remains module-first. This inventory adds function nodes only
for explicitly selected subsystems where decision ownership matters enough to
justify finer granularity. It intentionally does not expand every Python module
into a function graph.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

MISSION_COMPOSITION_ROOT = Path("backend/services/mission_composition")


@dataclass(frozen=True, slots=True)
class FunctionNode:
    id: str
    type: str
    source: str
    module: str
    name: str
    role: str | None = None


@dataclass(frozen=True, slots=True)
class FunctionEdge:
    source: str
    target: str
    type: str
    evidence: str


def _module_for_path(repo_root: Path, path: Path) -> str:
    rel = path.relative_to(repo_root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _function_id(module: str, name: str) -> str:
    return f"fn:{module}:{name}"


def _decision_role(module: str, name: str) -> str | None:
    roles = {
        (
            "backend.services.mission_composition.intent_interpreter",
            "_segment_clauses",
        ): "segments_text",
        (
            "backend.services.mission_composition.intent_interpreter",
            "_classify_clause",
        ): "classifies_materiality",
        (
            "backend.services.mission_composition.intent_interpreter",
            "interpret_instruction",
        ): "interprets_mission",
        (
            "backend.services.mission_composition.ability_vocab",
            "match_outcome_phrases",
        ): "maps_outcome",
        (
            "backend.services.mission_composition.ability_vocab",
            "phrase_maps_to_outcome",
        ): "maps_outcome",
        (
            "backend.services.mission_composition.interpretation.fuzzy",
            "fuzzy_outcome_candidates",
        ): "maps_fuzzy_outcome",
        (
            "backend.services.mission_composition.interpretation.normalize",
            "normalize_instruction_text",
        ): "normalizes_text",
    }
    return roles.get((module, name))


def _selected_python_files(repo_root: Path) -> list[Path]:
    root = repo_root / MISSION_COMPOSITION_ROOT
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return None


def _top_level_functions(
    tree: ast.Module,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _imported_function_aliases(
    tree: ast.Module,
    known_functions: dict[tuple[str, str], str],
) -> tuple[dict[str, str], dict[str, str]]:
    direct: dict[str, str] = {}
    modules: dict[str, str] = {}
    for item in tree.body:
        if isinstance(item, ast.ImportFrom) and item.level == 0 and item.module:
            for alias in item.names:
                target = known_functions.get((item.module, alias.name))
                if target:
                    direct[alias.asname or alias.name] = target
        elif isinstance(item, ast.Import):
            for alias in item.names:
                modules[alias.asname or alias.name.split(".")[0]] = alias.name
    return direct, modules


def _called_function_ids(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    module: str,
    local_functions: dict[str, str],
    direct_imports: dict[str, str],
    module_aliases: dict[str, str],
    known_functions: dict[tuple[str, str], str],
) -> set[str]:
    targets: set[str] = set()
    for item in ast.walk(function):
        if not isinstance(item, ast.Call):
            continue
        callee = item.func
        if isinstance(callee, ast.Name):
            if callee.id in local_functions:
                targets.add(local_functions[callee.id])
            elif callee.id in direct_imports:
                targets.add(direct_imports[callee.id])
        elif isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name):
            imported_module = module_aliases.get(callee.value.id)
            if imported_module:
                target = known_functions.get((imported_module, callee.attr))
                if target:
                    targets.add(target)
    return targets


def collect_function_graph(
    repo_root: Path,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Return selective function nodes and call/ownership edges."""

    parsed: dict[Path, ast.Module] = {}
    module_by_path: dict[Path, str] = {}
    known_functions: dict[tuple[str, str], str] = {}

    for path in _selected_python_files(repo_root):
        tree = _parse(path)
        if tree is None:
            continue
        module = _module_for_path(repo_root, path)
        parsed[path] = tree
        module_by_path[path] = module
        for function in _top_level_functions(tree):
            known_functions[(module, function.name)] = _function_id(module, function.name)

    nodes: list[dict[str, object]] = []
    edges: set[FunctionEdge] = set()

    for path, tree in parsed.items():
        module = module_by_path[path]
        source = str(path.relative_to(repo_root)).replace("\\", "/")
        local_functions = {
            function.name: known_functions[(module, function.name)] for function in _top_level_functions(tree)
        }
        direct_imports, module_aliases = _imported_function_aliases(tree, known_functions)

        for function in _top_level_functions(tree):
            node_id = known_functions[(module, function.name)]
            role = _decision_role(module, function.name)
            node: dict[str, object] = {
                "id": node_id,
                "type": "python_function",
                "source": source,
                "module": module,
                "name": function.name,
            }
            if role:
                node["decision_role"] = role
            nodes.append(node)
            edges.add(
                FunctionEdge(
                    source=node_id,
                    target=f"py:{module}",
                    type="defined_in",
                    evidence=source,
                )
            )
            for target in _called_function_ids(
                function,
                module=module,
                local_functions=local_functions,
                direct_imports=direct_imports,
                module_aliases=module_aliases,
                known_functions=known_functions,
            ):
                if target != node_id:
                    edges.add(
                        FunctionEdge(
                            source=node_id,
                            target=target,
                            type="calls_function",
                            evidence=source,
                        )
                    )

    rendered_edges = [
        {
            "from": edge.source,
            "to": edge.target,
            "type": edge.type,
            "evidence": edge.evidence,
        }
        for edge in sorted(
            edges,
            key=lambda item: (item.source, item.target, item.type, item.evidence),
        )
    ]
    return sorted(nodes, key=lambda node: str(node["id"])), rendered_edges


def collect_function_test_edges(
    repo_root: Path,
    function_nodes: list[dict[str, object]],
) -> list[dict[str, str]]:
    """Map direct named test imports to selective function nodes.

    Module-level ``tests`` edges remain canonical. These supplemental edges let
    impact analysis identify tests that directly exercise a specific function.
    """

    function_ids = {
        (str(node["module"]), str(node["name"])): str(node["id"])
        for node in function_nodes
        if node.get("module") and node.get("name")
    }
    tests_root = repo_root / "tests"
    if not tests_root.exists():
        return []

    edges: set[FunctionEdge] = set()
    for path in sorted(path for path in tests_root.rglob("*.py") if "__pycache__" not in path.parts):
        tree = _parse(path)
        if tree is None:
            continue
        source = str(path.relative_to(repo_root)).replace("\\", "/")
        test_id = f"test:{source}"
        for item in ast.walk(tree):
            if not isinstance(item, ast.ImportFrom) or item.level != 0 or not item.module:
                continue
            for alias in item.names:
                target = function_ids.get((item.module, alias.name))
                if target:
                    edges.add(
                        FunctionEdge(
                            source=test_id,
                            target=target,
                            type="tests_function",
                            evidence=source,
                        )
                    )
    return [
        {
            "from": edge.source,
            "to": edge.target,
            "type": edge.type,
            "evidence": edge.evidence,
        }
        for edge in sorted(
            edges,
            key=lambda item: (item.source, item.target, item.type, item.evidence),
        )
    ]
