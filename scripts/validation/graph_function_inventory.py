"""Selective symbol topology for architecture-critical Ajenda code.

The canonical graph remains module-first. This layer intentionally adds finer
resolution only where responsibility ownership matters: mission composition,
mission/ability routes, worker runtime state transitions, and the web/sales/GTM
action implementations targeted by the current architecture stabilization pass.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

MISSION_COMPOSITION_ROOT = Path("backend/services/mission_composition")
SELECTED_FILES = (
    Path("backend/services/worker_runtime_service.py"),
    Path("backend/api/routes/mission.py"),
    Path("backend/api/routes/ability_runtime.py"),
    Path("backend/services/tools/web_actions.py"),
    Path("backend/services/tools/sales_actions.py"),
    Path("backend/services/tools/gtm_actions.py"),
)
SELECTED_GLOBS = (
    "backend/services/worker_runtime_*.py",
    "backend/api/routes/mission_*.py",
    "backend/api/routes/ability_runtime_*.py",
    "backend/services/tools/web_action_*.py",
    "backend/services/tools/sales_action_*.py",
    "backend/services/tools/gtm_action_*.py",
)
HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})


@dataclass(frozen=True, slots=True)
class FunctionEdge:
    source: str
    target: str
    type: str
    evidence: str


@dataclass(frozen=True, slots=True)
class Symbol:
    node: ast.FunctionDef | ast.AsyncFunctionDef
    qualified_name: str
    owner_class: str | None = None
    enclosing_function: str | None = None


def _module_for_path(repo_root: Path, path: Path) -> str:
    rel = path.relative_to(repo_root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _function_id(module: str, qualified_name: str) -> str:
    return f"fn:{module}:{qualified_name}"


def _route_id(module: str, method: str, path: str) -> str:
    return f"route:{module}:{method.upper()}:{path or '/'}"


def _decision_role(module: str, name: str) -> str | None:
    return {
        ("backend.services.mission_composition.intent_interpreter", "_segment_clauses"): "segments_text",
        ("backend.services.mission_composition.intent_interpreter", "_classify_clause"): "classifies_materiality",
        ("backend.services.mission_composition.intent_interpreter", "interpret_instruction"): "interprets_mission",
        ("backend.services.mission_composition.ability_vocab", "match_outcome_phrases"): "maps_outcome",
        ("backend.services.mission_composition.ability_vocab", "phrase_maps_to_outcome"): "maps_outcome",
        (
            "backend.services.mission_composition.interpretation.fuzzy",
            "fuzzy_outcome_candidates",
        ): "maps_fuzzy_outcome",
        (
            "backend.services.mission_composition.interpretation.normalize",
            "normalize_instruction_text",
        ): "normalizes_text",
    }.get((module, name))


def _selected_python_files(repo_root: Path) -> list[Path]:
    files: set[Path] = set()
    composition = repo_root / MISSION_COMPOSITION_ROOT
    if composition.exists():
        files.update(path for path in composition.rglob("*.py") if "__pycache__" not in path.parts)
    files.update(repo_root / path for path in SELECTED_FILES if (repo_root / path).exists())
    for pattern in SELECTED_GLOBS:
        files.update(path for path in repo_root.glob(pattern) if path.is_file())
    return sorted(files)


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return None


def _nested_functions(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    prefix: str,
) -> list[Symbol]:
    result: list[Symbol] = []
    for child in function.body:
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        qualified = f"{prefix}.{child.name}"
        result.append(Symbol(child, qualified, enclosing_function=prefix))
        result.extend(_nested_functions(child, prefix=qualified))
    return result


def _symbols(tree: ast.Module) -> list[Symbol]:
    result: list[Symbol] = []
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.append(Symbol(item, item.name))
            result.extend(_nested_functions(item, prefix=item.name))
        elif isinstance(item, ast.ClassDef):
            result.extend(
                Symbol(child, f"{item.name}.{child.name}", owner_class=item.name)
                for child in item.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    return result


def _import_aliases(
    tree: ast.Module,
    known_top_level: dict[tuple[str, str], str],
) -> tuple[dict[str, str], dict[str, str]]:
    direct: dict[str, str] = {}
    modules: dict[str, str] = {}
    for item in tree.body:
        if isinstance(item, ast.ImportFrom) and item.level == 0 and item.module:
            for alias in item.names:
                target = known_top_level.get((item.module, alias.name))
                if target:
                    direct[alias.asname or alias.name] = target
        elif isinstance(item, ast.Import):
            for alias in item.names:
                modules[alias.asname or alias.name.split(".")[0]] = alias.name
    return direct, modules


def _calls_in_symbol(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    calls: list[ast.Call] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node is function:
                self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            if node is function:
                self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

        def visit_Call(self, node: ast.Call) -> None:
            calls.append(node)
            self.generic_visit(node)

    Visitor().visit(function)
    return calls


def _called_symbol_ids(
    symbol: Symbol,
    *,
    local_functions: dict[str, str],
    local_methods: dict[tuple[str, str], str],
    nested_functions: dict[tuple[str, str], str],
    direct_imports: dict[str, str],
    module_aliases: dict[str, str],
    known_top_level: dict[tuple[str, str], str],
) -> set[str]:
    targets: set[str] = set()
    for call in _calls_in_symbol(symbol.node):
        callee = call.func
        if isinstance(callee, ast.Name):
            nested = nested_functions.get((symbol.qualified_name, callee.id))
            if nested is None and symbol.enclosing_function:
                nested = nested_functions.get((symbol.enclosing_function, callee.id))
            target = nested or local_functions.get(callee.id) or direct_imports.get(callee.id)
            if target:
                targets.add(target)
        elif isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name):
            if callee.value.id in {"self", "cls"} and symbol.owner_class:
                target = local_methods.get((symbol.owner_class, callee.attr))
                if target:
                    targets.add(target)
                    continue
            imported_module = module_aliases.get(callee.value.id)
            if imported_module:
                target = known_top_level.get((imported_module, callee.attr))
                if target:
                    targets.add(target)
    return targets


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _router_prefix(tree: ast.Module) -> str:
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "router" for target in statement.targets):
            continue
        if not isinstance(statement.value, ast.Call):
            continue
        for keyword in statement.value.keywords:
            if keyword.arg == "prefix":
                return _literal_string(keyword.value) or ""
    return ""


def _route_contracts(
    *,
    tree: ast.Module,
    module: str,
    source: str,
    symbol_ids: dict[str, str],
) -> tuple[list[dict[str, object]], set[FunctionEdge]]:
    prefix = _router_prefix(tree)
    nodes: list[dict[str, object]] = []
    edges: set[FunctionEdge] = set()
    for item in tree.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        handler_id = symbol_ids.get(item.name)
        if not handler_id:
            continue
        for decorator in item.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "router"
                and func.attr.lower() in HTTP_METHODS
            ):
                continue
            relative = _literal_string(decorator.args[0]) if decorator.args else ""
            if relative is None:
                continue
            method = func.attr.upper()
            path = f"{prefix}{relative}" or "/"
            node_id = _route_id(module, method, path)
            nodes.append(
                {
                    "id": node_id,
                    "type": "http_route",
                    "source": source,
                    "module": module,
                    "method": method,
                    "path": path,
                    "handler": item.name,
                }
            )
            edges.add(FunctionEdge(node_id, handler_id, "handled_by", source))
            edges.add(FunctionEdge(node_id, f"py:{module}", "declared_in", source))
    return nodes, edges


def _action_handler_edges(
    *,
    tree: ast.Module,
    source: str,
    symbol_ids: dict[str, str],
    direct_imports: dict[str, str],
) -> set[FunctionEdge]:
    edges: set[FunctionEdge] = set()
    for item in ast.walk(tree):
        if not isinstance(item, ast.Call):
            continue
        func = item.func
        constructor = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if constructor != "ActionDefinition":
            continue
        action = _literal_string(next((kw.value for kw in item.keywords if kw.arg == "name"), None))
        handler = next((kw.value for kw in item.keywords if kw.arg == "handler"), None)
        if not action or not isinstance(handler, ast.Name):
            continue
        target = symbol_ids.get(handler.id) or direct_imports.get(handler.id)
        if target is None:
            matches = [
                node_id for qualified_name, node_id in symbol_ids.items() if qualified_name.endswith(f".{handler.id}")
            ]
            target = matches[0] if len(matches) == 1 else None
        if target:
            edges.add(FunctionEdge(f"action:{action}", target, "implemented_by", source))
    return edges


def collect_function_graph(
    repo_root: Path,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Return selective functions/methods plus route/action/call relationships."""

    parsed: dict[Path, ast.Module] = {}
    modules: dict[Path, str] = {}
    symbols_by_path: dict[Path, list[Symbol]] = {}
    known_top_level: dict[tuple[str, str], str] = {}

    for path in _selected_python_files(repo_root):
        tree = _parse(path)
        if tree is None:
            continue
        module = _module_for_path(repo_root, path)
        symbols = _symbols(tree)
        parsed[path] = tree
        modules[path] = module
        symbols_by_path[path] = symbols
        for symbol in symbols:
            if "." not in symbol.qualified_name:
                known_top_level[(module, symbol.node.name)] = _function_id(module, symbol.qualified_name)

    nodes: list[dict[str, object]] = []
    edges: set[FunctionEdge] = set()

    for path, tree in parsed.items():
        module = modules[path]
        source = str(path.relative_to(repo_root)).replace("\\", "/")
        symbols = symbols_by_path[path]
        symbol_ids = {symbol.qualified_name: _function_id(module, symbol.qualified_name) for symbol in symbols}
        local_functions = {
            symbol.node.name: symbol_ids[symbol.qualified_name]
            for symbol in symbols
            if "." not in symbol.qualified_name
        }
        local_methods = {
            (symbol.owner_class, symbol.node.name): symbol_ids[symbol.qualified_name]
            for symbol in symbols
            if symbol.owner_class
        }
        nested_functions = {
            (symbol.enclosing_function, symbol.node.name): symbol_ids[symbol.qualified_name]
            for symbol in symbols
            if symbol.enclosing_function
        }
        direct_imports, module_aliases = _import_aliases(tree, known_top_level)

        for symbol in symbols:
            node_id = symbol_ids[symbol.qualified_name]
            role = _decision_role(module, symbol.node.name)
            node: dict[str, object] = {
                "id": node_id,
                "type": "python_method" if symbol.owner_class else "python_function",
                "source": source,
                "module": module,
                "name": symbol.node.name,
                "qualified_name": symbol.qualified_name,
            }
            if symbol.owner_class:
                node["owner_class"] = symbol.owner_class
            if symbol.enclosing_function:
                node["enclosing_function"] = symbol.enclosing_function
            if role:
                node["decision_role"] = role
            nodes.append(node)
            edges.add(FunctionEdge(node_id, f"py:{module}", "defined_in", source))
            for target in _called_symbol_ids(
                symbol,
                local_functions=local_functions,
                local_methods=local_methods,
                nested_functions=nested_functions,
                direct_imports=direct_imports,
                module_aliases=module_aliases,
                known_top_level=known_top_level,
            ):
                if target != node_id:
                    edges.add(FunctionEdge(node_id, target, "calls_function", source))

        route_nodes, route_edges = _route_contracts(
            tree=tree,
            module=module,
            source=source,
            symbol_ids=symbol_ids,
        )
        nodes.extend(route_nodes)
        edges.update(route_edges)
        edges.update(
            _action_handler_edges(
                tree=tree,
                source=source,
                symbol_ids=symbol_ids,
                direct_imports=direct_imports,
            )
        )

    return (
        sorted(nodes, key=lambda node: str(node["id"])),
        [
            {
                "from": edge.source,
                "to": edge.target,
                "type": edge.type,
                "evidence": edge.evidence,
            }
            for edge in sorted(edges, key=lambda edge: (edge.source, edge.target, edge.type, edge.evidence))
        ],
    )


def _selected_class_methods(
    function_nodes: list[dict[str, object]],
) -> dict[tuple[str, str], dict[str, str]]:
    result: dict[tuple[str, str], dict[str, str]] = {}
    for node in function_nodes:
        if node.get("type") != "python_method":
            continue
        module = str(node.get("module") or "")
        owner = str(node.get("owner_class") or "")
        name = str(node.get("name") or "")
        if module and owner and name:
            result.setdefault((module, owner), {})[name] = str(node["id"])
    return result


def _imported_classes(
    tree: ast.Module,
    class_methods: dict[tuple[str, str], dict[str, str]],
) -> dict[str, dict[str, str]]:
    imported: dict[str, dict[str, str]] = {}
    for item in tree.body:
        if not isinstance(item, ast.ImportFrom) or item.level != 0 or not item.module:
            continue
        for alias in item.names:
            methods = class_methods.get((item.module, alias.name))
            if methods:
                imported[alias.asname or alias.name] = methods
    return imported


def _method_test_edges(
    tree: ast.Module,
    *,
    imported_classes: dict[str, dict[str, str]],
    test_id: str,
    source: str,
) -> set[FunctionEdge]:
    instances: dict[str, dict[str, str]] = {}
    for item in ast.walk(tree):
        if not isinstance(item, (ast.Assign, ast.AnnAssign)):
            continue
        value = item.value
        if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Name):
            continue
        methods = imported_classes.get(value.func.id)
        if not methods:
            continue
        targets = item.targets if isinstance(item, ast.Assign) else [item.target]
        for target in targets:
            if isinstance(target, ast.Name):
                instances[target.id] = methods

    edges: set[FunctionEdge] = set()
    for item in ast.walk(tree):
        if not isinstance(item, ast.Attribute):
            continue
        methods: dict[str, str] | None = None
        if isinstance(item.value, ast.Name):
            methods = instances.get(item.value.id) or imported_classes.get(item.value.id)
        elif isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Name):
            methods = imported_classes.get(item.value.func.id)
        if methods and item.attr in methods:
            edges.add(FunctionEdge(test_id, methods[item.attr], "tests_function", source))
    return edges


def collect_function_test_edges(
    repo_root: Path,
    function_nodes: list[dict[str, object]],
) -> list[dict[str, str]]:
    """Map direct imports and simple selected-class method references to tests."""

    top_level = {
        (str(node["module"]), str(node["name"])): str(node["id"])
        for node in function_nodes
        if node.get("type") == "python_function"
        and node.get("module")
        and node.get("name")
        and "." not in str(node.get("qualified_name", ""))
    }
    class_methods = _selected_class_methods(function_nodes)
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
                target = top_level.get((item.module, alias.name))
                if target:
                    edges.add(FunctionEdge(test_id, target, "tests_function", source))
        edges.update(
            _method_test_edges(
                tree,
                imported_classes=_imported_classes(tree, class_methods),
                test_id=test_id,
                source=source,
            )
        )

    return [
        {
            "from": edge.source,
            "to": edge.target,
            "type": edge.type,
            "evidence": edge.evidence,
        }
        for edge in sorted(edges, key=lambda edge: (edge.source, edge.target, edge.type, edge.evidence))
    ]
