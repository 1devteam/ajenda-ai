#!/usr/bin/env python3
"""Adjudicate GRAFT runtime binding candidates with source-backed witnesses.

This layer consumes the canonical graph's runtime-contract findings and reconciles
all currently authoritative static binding paths before assigning one of three
results:

- SATISFIED: the binding obligation is not runtime-applicable, or a source-backed
  binding reaches an accepted action input field.
- VIOLATED: the obligation is runtime-applicable and either no binding exists for
  the declared producer dependency or the compiler binds into a field forbidden by
  the registered action input model.
- INDETERMINATE: source truth is insufficient to prove either state.

The result is intentionally about the *artifact binding obligation*. It does not
claim that downstream business semantics, data quality, or mission success are
proven by a valid binding alone.
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

PLAN_COMPILER_PATH = Path("backend/services/mission_composition/plan_compiler.py")
TOOLS_ROOT = Path("backend/services/tools")
BINDING_FINDING_CLASS = "binding_coverage_gap"
RESULTS = frozenset({"SATISFIED", "VIOLATED", "INDETERMINATE"})
_UNKNOWN = object()


@dataclass(frozen=True, slots=True)
class BindingResolution:
    resolved: bool
    path: str | None


@dataclass(frozen=True, slots=True)
class InputModelRecord:
    model_name: str
    action_source: str


@dataclass(frozen=True, slots=True)
class ModelShape:
    name: str
    source: str
    fields: frozenset[str]
    bases: tuple[str, ...]
    extra_policy: str | None


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def _constructor_name(call: ast.Call) -> str:
    return (_call_name(call.func) or "").rsplit(".", 1)[-1]


def _keyword(call: ast.Call, name: str) -> ast.AST | None:
    return next((item.value for item in call.keywords if item.arg == name), None)


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_strings(node: ast.AST | None) -> tuple[str, ...]:
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        value = _literal_string(node)
        return (value,) if value is not None else ()
    values: list[str] = []
    for item in node.elts:
        value = _literal_string(item)
        if value is None:
            return ()
        values.append(value)
    return tuple(values)


def _eval_literal(node: ast.AST, env: dict[str, str]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        values = []
        for item in node.elts:
            value = _eval_literal(item, env)
            if value is _UNKNOWN:
                return _UNKNOWN
            values.append(value)
        return values
    return _UNKNOWN


def _eval_condition(node: ast.AST, env: dict[str, str]) -> bool | None:
    if isinstance(node, ast.BoolOp):
        values = [_eval_condition(value, env) for value in node.values]
        if isinstance(node.op, ast.And):
            if any(value is False for value in values):
                return False
            return True if all(value is True for value in values) else None
        if isinstance(node.op, ast.Or):
            if any(value is True for value in values):
                return True
            return False if all(value is False for value in values) else None
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _eval_condition(node.operand, env)
        return None if value is None else not value
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
        left = _eval_literal(node.left, env)
        right = _eval_literal(node.comparators[0], env)
        if left is _UNKNOWN or right is _UNKNOWN:
            return None
        op = node.ops[0]
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, ast.In):
            try:
                return left in right
            except TypeError:
                return None
        if isinstance(op, ast.NotIn):
            try:
                return left not in right
            except TypeError:
                return None
    return None


def _eval_return(node: ast.AST | None, env: dict[str, str]) -> tuple[bool, str | None]:
    if node is None:
        return True, None
    if isinstance(node, ast.Constant):
        if node.value is None:
            return True, None
        if isinstance(node.value, str):
            return True, node.value
        return False, None
    if isinstance(node, ast.JoinedStr):
        pieces: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                pieces.append(value.value)
                continue
            if isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name):
                resolved = env.get(value.value.id)
                if resolved is None:
                    return False, None
                pieces.append(resolved)
                continue
            return False, None
        return True, "".join(pieces)
    return False, None


def _execute_binding_statements(
    statements: list[ast.stmt], env: dict[str, str]
) -> tuple[bool, BindingResolution | None]:
    for statement in statements:
        if isinstance(statement, ast.Return):
            resolved, value = _eval_return(statement.value, env)
            return True, BindingResolution(resolved=resolved, path=value)
        if isinstance(statement, ast.If):
            condition = _eval_condition(statement.test, env)
            if condition is None:
                return True, BindingResolution(resolved=False, path=None)
            branch = statement.body if condition else statement.orelse
            returned, resolution = _execute_binding_statements(branch, env)
            if returned:
                return True, resolution
    return False, None


def compiler_binding_path(
    *, repo_root: Path, action_name: str, artifact: str
) -> BindingResolution:
    tree = _parse(repo_root / PLAN_COMPILER_PATH)
    function = next(
        (
            item
            for item in tree.body
            if isinstance(item, ast.FunctionDef) and item.name == "_binding_input_path"
        ),
        None,
    )
    if function is None:
        return BindingResolution(resolved=False, path=None)
    returned, resolution = _execute_binding_statements(
        function.body, {"action_name": action_name, "output_name": artifact}
    )
    if not returned or resolution is None:
        return BindingResolution(resolved=False, path=None)
    return resolution


def _action_input_models(repo_root: Path) -> dict[str, InputModelRecord]:
    records: dict[str, InputModelRecord] = {}
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
            model_node = _keyword(node, "input_model")
            model_name = (
                (_call_name(model_node) or "").rsplit(".", 1)[-1]
                if model_node is not None
                else ""
            )
            if not action or not model_name:
                continue
            record = InputModelRecord(model_name=model_name, action_source=source)
            records[action] = record
            for alias in _literal_strings(_keyword(node, "aliases")):
                records[alias] = record
    return records


def _extra_policy(class_node: ast.ClassDef) -> str | None:
    for statement in class_node.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets: list[ast.expr] = []
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        else:
            targets = [statement.target]
            value = statement.value
        if not any(
            isinstance(target, ast.Name) and target.id == "model_config"
            for target in targets
        ):
            continue
        if not isinstance(value, ast.Call) or _constructor_name(value) != "ConfigDict":
            continue
        return _literal_string(_keyword(value, "extra"))
    return None


def _model_shapes(repo_root: Path) -> dict[str, ModelShape]:
    shapes: dict[str, ModelShape] = {}
    root = repo_root / TOOLS_ROOT
    for path in sorted(root.rglob("*.py")):
        try:
            tree = _parse(path)
        except (OSError, SyntaxError):
            continue
        source = str(path.relative_to(repo_root)).replace("\\", "/")
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            fields = {
                statement.target.id
                for statement in node.body
                if isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
            }
            bases = tuple(
                name.rsplit(".", 1)[-1]
                for base in node.bases
                if (name := _call_name(base)) is not None
            )
            shapes[node.name] = ModelShape(
                name=node.name,
                source=source,
                fields=frozenset(fields),
                bases=bases,
                extra_policy=_extra_policy(node),
            )
    return shapes


def _all_model_fields(
    model_name: str,
    shapes: dict[str, ModelShape],
    seen: set[str] | None = None,
) -> set[str]:
    seen = set(seen or set())
    if model_name in seen:
        return set()
    seen.add(model_name)
    shape = shapes.get(model_name)
    if shape is None:
        return set()
    fields = set(shape.fields)
    for base in shape.bases:
        fields.update(_all_model_fields(base, shapes, seen))
    return fields


def _top_level_input_key(path: str) -> str | None:
    raw = path.strip()
    if raw in {"$", "$.input", "input"}:
        return None
    if raw.startswith("$.input."):
        remainder = raw[len("$.input.") :]
    elif raw.startswith("$."):
        remainder = raw[2:]
        if remainder.startswith("input."):
            remainder = remainder[len("input.") :]
    else:
        remainder = raw
    key = remainder.split(".", 1)[0].strip()
    return key or None


def _schema_acceptance(
    *,
    action_name: str,
    input_path: str,
    action_models: dict[str, InputModelRecord],
    shapes: dict[str, ModelShape],
) -> dict[str, Any]:
    key = _top_level_input_key(input_path)
    if key is None:
        return {
            "status": "accepted",
            "top_level_key": None,
            "reason": "binding targets the input root",
        }
    record = action_models.get(action_name)
    if record is None:
        return {
            "status": "indeterminate",
            "top_level_key": key,
            "reason": "registered action input model was not statically resolved",
        }
    shape = shapes.get(record.model_name)
    if shape is None:
        return {
            "status": "indeterminate",
            "top_level_key": key,
            "input_model": record.model_name,
            "reason": "input model class was not found in the dependency-light tool schema inventory",
        }
    fields = _all_model_fields(record.model_name, shapes)
    if key in fields:
        return {
            "status": "accepted",
            "top_level_key": key,
            "input_model": record.model_name,
            "input_model_source": shape.source,
            "reason": f"input model declares top-level field {key}",
        }
    if shape.extra_policy == "forbid":
        return {
            "status": "rejected",
            "top_level_key": key,
            "input_model": record.model_name,
            "input_model_source": shape.source,
            "reason": f"input model forbids undeclared top-level field {key}",
        }
    return {
        "status": "indeterminate",
        "top_level_key": key,
        "input_model": record.model_name,
        "input_model_source": shape.source,
        "reason": f"input model does not declare {key} and extra-field behavior is not proven safe",
    }


def _node_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): node for node in graph.get("nodes", [])}


def _edge_index(graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for edge in graph.get("edges", []):
        index.setdefault(str(edge["from"]), []).append(edge)
    return index


def _producer_dependency(
    *,
    job_id: str,
    artifact_id: str,
    nodes: dict[str, dict[str, Any]],
    edges_by_source: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    artifact = nodes.get(artifact_id, {})
    producers = artifact.get("producers") or []
    producer_ids = {f"job:{item}" for item in producers if isinstance(item, str)}
    for edge in edges_by_source.get(job_id, []):
        if str(edge.get("to")) not in producer_ids:
            continue
        edge_type = str(edge.get("type") or "")
        if edge_type.startswith("depends_on_"):
            return edge
    return None


def _existing_binding(
    *,
    action_id: str,
    artifact_id: str,
    edges_by_source: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    for edge in edges_by_source.get(action_id, []):
        if edge.get("type") == "binds_artifact" and str(edge.get("to")) == artifact_id:
            return edge
    return None


def adjudicate_runtime_binding_candidates(
    graph: dict[str, Any], *, repo_root: Path = REPO_ROOT
) -> dict[str, Any]:
    nodes = _node_map(graph)
    edges_by_source = _edge_index(graph)
    action_models = _action_input_models(repo_root)
    shapes = _model_shapes(repo_root)
    results: list[dict[str, Any]] = []

    for finding in graph.get("semantic_findings", []):
        if finding.get("classification") != BINDING_FINDING_CLASS:
            continue
        related = [str(item) for item in finding.get("related_nodes", [])]
        if len(related) != 3:
            results.append(
                {
                    "finding_id": finding.get("id"),
                    "result": "INDETERMINATE",
                    "reason": "binding candidate does not identify exactly job/action/artifact nodes",
                }
            )
            continue
        job_id, action_id, artifact_id = related
        job = nodes.get(job_id, {})
        action = nodes.get(action_id, {})
        artifact = nodes.get(artifact_id, {})
        action_name = str(action.get("label") or action_id.removeprefix("action:"))
        artifact_name = str(
            artifact.get("label") or artifact_id.removeprefix("artifact:")
        )
        dependency = _producer_dependency(
            job_id=job_id,
            artifact_id=artifact_id,
            nodes=nodes,
            edges_by_source=edges_by_source,
        )
        evidence = finding.get("evidence", [])
        base: dict[str, Any] = {
            "finding_id": finding.get("id"),
            "job": job_id.removeprefix("job:"),
            "action": action_name,
            "artifact": artifact_name,
            "job_maturity": job.get("maturity"),
            "dependency": dependency,
            "witness_sources": sorted(
                {str(item) for item in evidence if item}
                if isinstance(evidence, list)
                else set()
            ),
        }

        if job.get("maturity") != "runtime_bound":
            results.append(
                {
                    **base,
                    "result": "SATISFIED",
                    "applicability": False,
                    "reason": "job is not runtime_bound, so no runtime artifact-binding obligation is active",
                }
            )
            continue

        existing = _existing_binding(
            action_id=action_id,
            artifact_id=artifact_id,
            edges_by_source=edges_by_source,
        )
        compiler = compiler_binding_path(
            repo_root=repo_root,
            action_name=action_name,
            artifact=artifact_name,
        )
        binding: dict[str, Any] | None = None
        if existing is not None:
            binding = {
                "source": existing.get("evidence"),
                "phase": "runtime_fallback",
                "input_path": existing.get("input_path"),
                "output_path": existing.get("output_path"),
            }
        elif compiler.resolved and compiler.path is not None:
            binding = {
                "source": str(PLAN_COMPILER_PATH).replace("\\", "/"),
                "phase": "plan_compile",
                "input_path": compiler.path,
                "output_path": f"$.{artifact_name}",
            }

        if binding is not None and isinstance(binding.get("input_path"), str):
            schema = _schema_acceptance(
                action_name=action_name,
                input_path=str(binding["input_path"]),
                action_models=action_models,
                shapes=shapes,
            )
            witness_sources = set(base["witness_sources"])
            source = binding.get("source")
            if isinstance(source, str) and source:
                witness_sources.add(source)
            if isinstance(schema.get("input_model_source"), str):
                witness_sources.add(str(schema["input_model_source"]))
            if schema["status"] == "accepted":
                results.append(
                    {
                        **base,
                        "result": "SATISFIED",
                        "applicability": True,
                        "binding": binding,
                        "schema": schema,
                        "witness_sources": sorted(witness_sources),
                        "reason": "source-backed binding reaches a field accepted by the registered action input model",
                    }
                )
                continue
            if schema["status"] == "rejected":
                results.append(
                    {
                        **base,
                        "result": "VIOLATED",
                        "applicability": True,
                        "binding": binding,
                        "schema": schema,
                        "witness_sources": sorted(witness_sources),
                        "reason": "compiler/runtime binding targets a field rejected by the registered action input model",
                    }
                )
                continue
            results.append(
                {
                    **base,
                    "result": "INDETERMINATE",
                    "applicability": True,
                    "binding": binding,
                    "schema": schema,
                    "witness_sources": sorted(witness_sources),
                    "reason": "binding exists but schema acceptance cannot be proven statically",
                }
            )
            continue

        if compiler.resolved and compiler.path is None and dependency is not None:
            dependency_kind = str(dependency.get("type") or "").removeprefix(
                "depends_on_"
            )
            results.append(
                {
                    **base,
                    "result": "VIOLATED",
                    "applicability": True,
                    "compiler_binding": None,
                    "dependency_kind": dependency_kind,
                    "witness_sources": sorted(
                        set(base["witness_sources"])
                        | {str(PLAN_COMPILER_PATH).replace("\\", "/")}
                    ),
                    "reason": "declared producer dependency can require the artifact, but compiler explicitly emits no binding",
                }
            )
            continue

        results.append(
            {
                **base,
                "result": "INDETERMINATE",
                "applicability": True,
                "reason": "no complete source-backed binding or violation witness could be established",
            }
        )

    counts = {result: 0 for result in sorted(RESULTS)}
    for item in results:
        counts[str(item["result"])] += 1
    return {
        "schema_version": "1.0",
        "scope": "runtime-artifact-binding-obligations",
        "graph_schema_version": graph.get("schema_version"),
        "results": sorted(results, key=lambda item: str(item.get("finding_id"))),
        "metrics": {
            "candidate_count": len(results),
            "satisfied_count": counts["SATISFIED"],
            "violated_count": counts["VIOLATED"],
            "indeterminate_count": counts["INDETERMINATE"],
        },
        "policy": {
            "enforcement": "disabled",
            "note": "Adjudication evidence only; no result is an automatic merge gate in schema 1.0.",
        },
    }


def _print_human(report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    print(
        "GRAFT runtime binding adjudication: "
        f"{metrics['candidate_count']} candidate(s), "
        f"{metrics['satisfied_count']} satisfied, "
        f"{metrics['violated_count']} violated, "
        f"{metrics['indeterminate_count']} indeterminate"
    )
    for item in report["results"]:
        print(f"{item['result']}: {item['finding_id']} — {item['reason']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Adjudicate GRAFT runtime artifact-binding findings."
    )
    parser.add_argument("--graph")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.graph:
        graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    else:
        graph = build_graph()
    report = adjudicate_runtime_binding_candidates(graph)
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
