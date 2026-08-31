#!/usr/bin/env python3
"""Refine GRAFT binding adjudication with typed behavioral-consumption evidence.

A binding that lands on a schema-accepted field is not automatically useful. This
layer asks whether the bound path is actually read by the action's registered handler
or by an action-applicable runtime input specializer before handler invocation.

The analysis is intentionally conservative:
- an exact/descendant read proves consumption;
- a dynamic escape of an ancestor container is INDETERMINATE;
- no read or escape on the typed behavior path proves the binding is unconsumed.

Raw ToolInvocation envelope access does not satisfy a typed artifact-binding
obligation. If an action needs bound data, that dependency should be visible through
the validated input model or the canonical input-specialization path.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_DIR = Path(__file__).resolve().parent
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from build_dependency_graph import build_graph  # noqa: E402
from graph_runtime_contract_adjudication import (  # noqa: E402
    REPO_ROOT as ADJUDICATOR_REPO_ROOT,
)
from graph_runtime_contract_adjudication import (  # noqa: E402
    _call_name,
    _constructor_name,
    _eval_condition,
    _keyword,
    _literal_string,
    _literal_strings,
    adjudicate_runtime_binding_candidates,
)

RUNTIME_BINDING_PATH = Path("backend/services/tools/mission_input_binding.py")
TOOLS_ROOT = Path("backend/services/tools")
SAFE_ALIAS_CALLS = frozenset(
    {
        "bool",
        "deepcopy",
        "dict",
        "isinstance",
        "len",
        "list",
        "set",
        "str",
        "tuple",
    }
)


@dataclass(frozen=True, slots=True)
class ActionBehavior:
    action_name: str
    handler_name: str
    source: str


@dataclass(frozen=True, slots=True)
class ConsumptionEvidence:
    status: str
    source: str
    function: str
    target_path: tuple[str, ...]
    reads: tuple[tuple[str, ...], ...]
    ambiguous_escapes: tuple[tuple[str, ...], ...]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    return next(
        (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name),
        None,
    )


def _registered_action_behaviors(repo_root: Path) -> dict[str, ActionBehavior]:
    behaviors: dict[str, ActionBehavior] = {}
    root = repo_root / TOOLS_ROOT
    for path in sorted(root.rglob("*.py")):
        try:
            tree = _parse(path)
        except (OSError, SyntaxError):
            continue
        source = str(path.relative_to(repo_root)).replace("\\", "/")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _constructor_name(node) != "ActionDefinition":
                continue
            action = _literal_string(_keyword(node, "name"))
            handler_node = _keyword(node, "handler")
            handler_name = (_call_name(handler_node) or "").rsplit(".", 1)[-1]
            if not action or not handler_name:
                continue
            record = ActionBehavior(action_name=action, handler_name=handler_name, source=source)
            behaviors[action] = record
            for alias in _literal_strings(_keyword(node, "aliases")):
                behaviors[alias] = ActionBehavior(
                    action_name=alias,
                    handler_name=handler_name,
                    source=source,
                )
    return behaviors


def _path_from_input_path(path: str) -> tuple[str, ...]:
    raw = path.strip()
    if raw in {"$", "$.input", "input"}:
        return ()
    if raw.startswith("$.input."):
        raw = raw[len("$.input.") :]
    elif raw.startswith("$."):
        raw = raw[2:]
        if raw.startswith("input."):
            raw = raw[len("input.") :]
    return tuple(part for part in raw.split(".") if part)


def _is_empty_container(node: ast.AST) -> bool:
    return (
        isinstance(node, (ast.Dict, ast.List, ast.Set, ast.Tuple))
        and not getattr(node, "elts", None)
        and not getattr(node, "keys", None)
    )


def _expr_alias_path(node: ast.AST, aliases: dict[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if isinstance(node, ast.Attribute):
        base = _expr_alias_path(node.value, aliases)
        return None if base is None else (*base, node.attr)
    if isinstance(node, ast.Subscript):
        base = _expr_alias_path(node.value, aliases)
        if base is None:
            return None
        key_node = node.slice
        key = _literal_string(key_node)
        return None if key is None else (*base, key)
    if isinstance(node, ast.Call):
        name = (_call_name(node.func) or "").rsplit(".", 1)[-1]
        if name in {"dict", "deepcopy"} and node.args:
            return _expr_alias_path(node.args[0], aliases)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            base = _expr_alias_path(node.func.value, aliases)
            key = _literal_string(node.args[0]) if node.args else None
            return None if base is None or key is None else (*base, key)
        return None
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        resolved_paths: list[tuple[str, ...]] = []
        for value in node.values:
            path = _expr_alias_path(value, aliases)
            if path is not None:
                resolved_paths.append(path)
                continue
            if _is_empty_container(value) or isinstance(value, ast.Constant):
                continue
            return None
        if resolved_paths and all(path == resolved_paths[0] for path in resolved_paths):
            return resolved_paths[0]
    if isinstance(node, ast.IfExp):
        body = _expr_alias_path(node.body, aliases)
        other = _expr_alias_path(node.orelse, aliases)
        if body == other:
            return body
        if body is not None and (_is_empty_container(node.orelse) or isinstance(node.orelse, ast.Constant)):
            return body
        if other is not None and (_is_empty_container(node.body) or isinstance(node.body, ast.Constant)):
            return other
    return None


def _assignment_target(statement: ast.AST) -> tuple[str | None, ast.AST | None]:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        return statement.targets[0].id, statement.value
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return statement.target.id, statement.value
    return None, None


def _input_aliases(function: ast.FunctionDef, *, explicit_roots: set[str] | None = None) -> dict[str, tuple[str, ...]]:
    aliases = {name: () for name in (explicit_roots or set())}

    for node in ast.walk(function):
        target, value = _assignment_target(node)
        if target is None or not isinstance(value, ast.Call):
            continue
        if not isinstance(value.func, ast.Attribute) or value.func.attr != "model_validate":
            continue
        if not value.args:
            continue
        arg = value.args[0]
        if isinstance(arg, ast.Attribute) and arg.attr == "input":
            aliases[target] = ()

    changed = True
    while changed:
        changed = False
        for node in ast.walk(function):
            target, value = _assignment_target(node)
            if target is None or value is None:
                continue
            path = _expr_alias_path(value, aliases)
            if path is not None and aliases.get(target) != path:
                aliases[target] = path
                changed = True
    return aliases


def _is_prefix(prefix: tuple[str, ...], value: tuple[str, ...]) -> bool:
    return len(prefix) <= len(value) and value[: len(prefix)] == prefix


def _function_consumption(
    *,
    function: ast.FunctionDef,
    source: str,
    target_path: tuple[str, ...],
    explicit_roots: set[str] | None = None,
) -> ConsumptionEvidence:
    aliases = _input_aliases(function, explicit_roots=explicit_roots)
    reads: set[tuple[str, ...]] = set()
    escapes: set[tuple[str, ...]] = set()

    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            base = _expr_alias_path(node.func.value, aliases)
            key = _literal_string(node.args[0]) if node.args else None
            if base is not None and key is not None:
                reads.add((*base, key))
                continue

        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
            path = _expr_alias_path(node, aliases)
            if path is not None:
                reads.add(path)
            elif (base := _expr_alias_path(node.value, aliases)) is not None and _is_prefix(base, target_path):
                escapes.add(base)

        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            path = _expr_alias_path(node, aliases)
            if path is not None:
                reads.add(path)

        if not isinstance(node, ast.Call):
            continue
        call_name = (_call_name(node.func) or "").rsplit(".", 1)[-1]
        if call_name in SAFE_ALIAS_CALLS:
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            continue

        receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
        if receiver is not None:
            receiver_path = _expr_alias_path(receiver, aliases)
            if receiver_path is not None and _is_prefix(receiver_path, target_path):
                keys_above_target_parent = (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "keys"
                    and len(receiver_path) + 1 < len(target_path)
                )
                if not keys_above_target_parent:
                    escapes.add(receiver_path)

        for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
            path = _expr_alias_path(argument, aliases)
            if path is not None and _is_prefix(path, target_path):
                escapes.add(path)

    exact_reads = sorted(path for path in reads if _is_prefix(target_path, path))
    if exact_reads:
        status = "consumed"
    elif escapes:
        status = "indeterminate"
    else:
        status = "unconsumed"
    return ConsumptionEvidence(
        status=status,
        source=source,
        function=function.name,
        target_path=target_path,
        reads=tuple(sorted(reads)),
        ambiguous_escapes=tuple(sorted(escapes)),
    )


def _specializers_for_action(repo_root: Path, action_name: str) -> tuple[list[str], bool]:
    tree = _parse(repo_root / RUNTIME_BINDING_PATH)
    function = _function(tree, "apply_input_bindings")
    if function is None:
        return [], False

    selected: list[str] = []
    fully_resolved = True

    def specializer_names(statement: ast.AST) -> list[str]:
        names: list[str] = []
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue
            name = (_call_name(node.func) or "").rsplit(".", 1)[-1]
            if name.startswith("_specialize_") and name not in names:
                names.append(name)
        return names

    def visit(statements: list[ast.stmt]) -> None:
        nonlocal fully_resolved
        for statement in statements:
            if isinstance(statement, ast.If):
                if not specializer_names(statement):
                    continue
                decision = _eval_condition(statement.test, {"action_name": action_name})
                if decision is True:
                    visit(statement.body)
                elif decision is False:
                    visit(statement.orelse)
                else:
                    fully_resolved = False
                continue
            for name in specializer_names(statement):
                if name not in selected:
                    selected.append(name)

    visit(function.body)
    return selected, fully_resolved


def _consumption_witness(
    *,
    repo_root: Path,
    action_name: str,
    input_path: str,
    behaviors: dict[str, ActionBehavior],
) -> dict[str, Any]:
    target = _path_from_input_path(input_path)
    if not target:
        return {
            "status": "indeterminate",
            "target_path": list(target),
            "reason": "binding targets the entire input root; semantic consumption cannot be isolated",
        }

    evidence: list[ConsumptionEvidence] = []
    specializers, specializer_control_resolved = _specializers_for_action(repo_root, action_name)
    binding_tree = _parse(repo_root / RUNTIME_BINDING_PATH)
    binding_source = str(RUNTIME_BINDING_PATH).replace("\\", "/")
    for name in specializers:
        function = _function(binding_tree, name)
        if function is None:
            continue
        root = function.args.args[0].arg if function.args.args else "bound"
        evidence.append(
            _function_consumption(
                function=function,
                source=binding_source,
                target_path=target,
                explicit_roots={root},
            )
        )

    behavior = behaviors.get(action_name)
    if behavior is None:
        return {
            "status": "indeterminate",
            "target_path": list(target),
            "specializers": specializers,
            "reason": "registered action handler could not be statically resolved",
        }
    handler_tree = _parse(repo_root / behavior.source)
    handler = _function(handler_tree, behavior.handler_name)
    if handler is None:
        return {
            "status": "indeterminate",
            "target_path": list(target),
            "handler_source": behavior.source,
            "handler": behavior.handler_name,
            "specializers": specializers,
            "reason": "registered action handler function was not found in its source module",
        }
    evidence.append(
        _function_consumption(
            function=handler,
            source=behavior.source,
            target_path=target,
        )
    )

    serialized = [
        {
            "status": item.status,
            "source": item.source,
            "function": item.function,
            "target_path": list(item.target_path),
            "reads": [list(path) for path in item.reads],
            "ambiguous_escapes": [list(path) for path in item.ambiguous_escapes],
        }
        for item in evidence
    ]
    if any(item.status == "consumed" for item in evidence):
        return {
            "status": "consumed",
            "target_path": list(target),
            "specializer_control_resolved": specializer_control_resolved,
            "evidence": serialized,
            "reason": "typed binding path is read by an applicable specializer or registered handler",
        }
    if not specializer_control_resolved or any(item.status == "indeterminate" for item in evidence):
        return {
            "status": "indeterminate",
            "target_path": list(target),
            "specializer_control_resolved": specializer_control_resolved,
            "evidence": serialized,
            "reason": "typed behavior path contains dynamic consumption that cannot be resolved statically",
        }
    return {
        "status": "unconsumed",
        "target_path": list(target),
        "specializer_control_resolved": specializer_control_resolved,
        "evidence": serialized,
        "reason": "no applicable specializer or registered handler reads the bound typed input path",
    }


def adjudicate_runtime_contracts_with_consumption(
    graph: dict[str, Any], *, repo_root: Path = ADJUDICATOR_REPO_ROOT
) -> dict[str, Any]:
    base = adjudicate_runtime_binding_candidates(graph, repo_root=repo_root)
    behaviors = _registered_action_behaviors(repo_root)
    refined: list[dict[str, Any]] = []

    for item in base["results"]:
        current = dict(item)
        if current.get("result") != "SATISFIED" or current.get("binding_disposition") != "COMPATIBLE_WHEN_APPLICABLE":
            refined.append(current)
            continue
        binding = current.get("binding")
        input_path = binding.get("input_path") if isinstance(binding, dict) else None
        if not isinstance(input_path, str):
            current["result"] = "INDETERMINATE"
            current["binding_disposition"] = "CONSUMPTION_UNRESOLVED"
            current["reason"] = "schema-compatible binding has no statically checkable input path"
            refined.append(current)
            continue

        consumption = _consumption_witness(
            repo_root=repo_root,
            action_name=str(current.get("action") or ""),
            input_path=input_path,
            behaviors=behaviors,
        )
        current["consumption"] = consumption
        witness_sources = set(str(value) for value in current.get("witness_sources", []) if value)
        for evidence in consumption.get("evidence", []):
            source = evidence.get("source") if isinstance(evidence, dict) else None
            if isinstance(source, str) and source:
                witness_sources.add(source)
        current["witness_sources"] = sorted(witness_sources)

        if consumption["status"] == "consumed":
            current["binding_disposition"] = "CONSUMED_WHEN_APPLICABLE"
            current["reason"] = "source-backed binding is schema-compatible and reaches typed runtime behavior"
        elif consumption["status"] == "unconsumed":
            current["result"] = "VIOLATED"
            current["binding_disposition"] = "UNCONSUMED_WHEN_APPLICABLE"
            current["reason"] = "binding is schema-compatible but does not reach the typed runtime behavior path"
        else:
            current["result"] = "INDETERMINATE"
            current["binding_disposition"] = "CONSUMPTION_UNRESOLVED"
            current["reason"] = str(consumption["reason"])
        refined.append(current)

    counts = {result: 0 for result in ("SATISFIED", "VIOLATED", "INDETERMINATE")}
    for item in refined:
        counts[str(item["result"])] += 1
    return {
        "schema_version": "1.2",
        "scope": "runtime-artifact-binding-and-typed-consumption",
        "graph_schema_version": graph.get("schema_version"),
        "results": sorted(refined, key=lambda item: str(item.get("finding_id"))),
        "metrics": {
            "candidate_count": len(refined),
            "satisfied_count": counts["SATISFIED"],
            "violated_count": counts["VIOLATED"],
            "indeterminate_count": counts["INDETERMINATE"],
        },
        "policy": {
            "enforcement": "disabled",
            "applicability_instantiation": "required-for-conditional-enforcement",
            "typed_consumption_required": True,
            "note": (
                "Evidence only. SATISFIED requires schema compatibility plus typed behavioral consumption. "
                "Conditional dispositions still require mission/plan instantiation before enforcement."
            ),
        },
    }


def _print_human(report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    print(
        "GRAFT runtime contract adjudication: "
        f"{metrics['candidate_count']} candidate(s), "
        f"{metrics['satisfied_count']} satisfied, "
        f"{metrics['violated_count']} violated, "
        f"{metrics['indeterminate_count']} indeterminate"
    )
    for item in report["results"]:
        applicability = item.get("applicability", {}).get("state", "unresolved")
        print(
            f"{item['result']}: {item['finding_id']} "
            f"[{applicability}; {item.get('binding_disposition')}] — {item['reason']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Adjudicate GRAFT runtime binding and typed-consumption findings.")
    parser.add_argument("--graph")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.graph:
        graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    else:
        graph = build_graph()
    report = adjudicate_runtime_contracts_with_consumption(graph)
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
    raise SystemExit(main())
