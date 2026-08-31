#!/usr/bin/env python3
"""Adjudicate GRAFT runtime artifact-binding candidates with source-backed witnesses.

This layer consumes the canonical graph's runtime-contract candidates and reconciles
Ajenda's authoritative static binding paths before assigning one of three results:

- SATISFIED: the runtime obligation is inactive, or the binding is structurally
  compatible whenever its dependency becomes applicable.
- VIOLATED: a binding obligation has a source-backed structural defect whenever its
  dependency becomes applicable.
- INDETERMINATE: source truth is insufficient to prove either state.

Applicability is recorded separately. A conditional dependency can therefore be
VIOLATED *when applicable* without claiming that a particular mission activates it.
A mission-specific applicability decision requires an instantiated GRAFT slice with
that mission's structured intent/world-state.

The result is intentionally limited to artifact binding. It does not prove data
quality, downstream viability, mission completion, or business correctness.
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
RUNTIME_BINDING_PATH = Path("backend/services/tools/mission_input_binding.py")
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


def compiler_binding_path(*, repo_root: Path, action_name: str, artifact: str) -> BindingResolution:
    """Statically evaluate the authoritative plan-time binding function."""

    tree = _parse(repo_root / PLAN_COMPILER_PATH)
    function = next(
        (item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "_binding_input_path"),
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
            model_name = (_call_name(model_node) or "").rsplit(".", 1)[-1] if model_node is not None else ""
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
        if not any(isinstance(target, ast.Name) and target.id == "model_config" for target in targets):
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
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
            }
            bases = tuple(name.rsplit(".", 1)[-1] for base in node.bases if (name := _call_name(base)) is not None)
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
    matches: list[dict[str, Any]] = []
    for edge in edges_by_source.get(job_id, []):
        if str(edge.get("to")) not in producer_ids:
            continue
        edge_type = str(edge.get("type") or "")
        if edge_type.startswith("depends_on_"):
            matches.append(edge)
    if len(matches) == 1:
        return matches[0]
    return None


def _fallback_binding(
    *,
    action_id: str,
    artifact_id: str,
    edges_by_source: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    for edge in edges_by_source.get(action_id, []):
        if edge.get("type") == "binds_artifact" and str(edge.get("to")) == artifact_id:
            return edge
    return None


def _applicability(*, job: dict[str, Any], dependency: dict[str, Any] | None) -> dict[str, Any]:
    """Describe static applicability without pretending an uninstantiated condition is active."""

    if job.get("maturity") != "runtime_bound":
        return {
            "state": "inactive",
            "decision": "static",
            "reason": "job is not runtime_bound",
        }
    if dependency is None:
        return {
            "state": "unresolved",
            "decision": "static",
            "reason": "a unique producer dependency was not established",
        }
    edge_type = str(dependency.get("type") or "")
    kind = edge_type.removeprefix("depends_on_") if edge_type.startswith("depends_on_") else edge_type
    if kind in {"hard", "legacy"}:
        return {
            "state": "always_when_job_selected",
            "decision": "static",
            "dependency_kind": kind,
            "reason": "producer dependency is mandatory whenever the consumer job is selected",
        }
    if kind == "conditional":
        return {
            "state": "conditional",
            "decision": "requires_instantiated_inputs",
            "dependency_kind": kind,
            "required_when_missing": list(dependency.get("required_when_missing") or []),
            "satisfied_by": list(dependency.get("satisfied_by") or []),
            "reason": "activation depends on the instantiated intent/world-state satisfiers",
        }
    if kind == "optional":
        return {
            "state": "conditional_on_co_selection",
            "decision": "requires_instantiated_plan",
            "dependency_kind": kind,
            "reason": "optional producer is not automatically expanded but may be independently co-selected",
        }
    return {
        "state": "unresolved",
        "decision": "static",
        "dependency_kind": kind,
        "reason": "dependency kind is not understood by this adjudicator",
    }


def _finding_sources(finding: dict[str, Any]) -> set[str]:
    evidence = finding.get("evidence", [])
    if not isinstance(evidence, list):
        return set()
    return {str(item) for item in evidence if item}


def _binding_witness(
    *,
    repo_root: Path,
    action_name: str,
    artifact_name: str,
    fallback: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve plan-time binding first; fallback cannot silently override explicit metadata.

    `mission_input_binding._binding_specs_from_metadata` consumes non-empty explicit
    `input_bindings` before considering fallback defaults. A fallback-only path is
    therefore not enough to prove satisfaction when plan-time resolution is unknown
    or explicitly omits this artifact: whether fallback runs depends on the complete
    instantiated step's metadata.
    """

    compiler = compiler_binding_path(
        repo_root=repo_root,
        action_name=action_name,
        artifact=artifact_name,
    )
    compiler_source = str(PLAN_COMPILER_PATH).replace("\\", "/")
    fallback_source = str(RUNTIME_BINDING_PATH).replace("\\", "/")

    if not compiler.resolved:
        return {
            "status": "indeterminate",
            "plan_compile": {"resolved": False, "source": compiler_source},
            "runtime_fallback": fallback,
            "reason": "plan-time binding logic could not be statically resolved",
            "witness_sources": [compiler_source, fallback_source],
        }
    if compiler.path is not None:
        return {
            "status": "bound",
            "phase": "plan_compile",
            "input_path": compiler.path,
            "output_path": f"$.{artifact_name}",
            "source": compiler_source,
            "runtime_fallback": fallback,
            "witness_sources": [compiler_source, fallback_source],
        }
    if fallback is not None:
        return {
            "status": "indeterminate",
            "plan_compile": {"resolved": True, "input_path": None, "source": compiler_source},
            "runtime_fallback": fallback,
            "reason": (
                "compiler omits this artifact while fallback exists; fallback executes only when the "
                "complete explicit input_bindings list is absent, which requires an instantiated plan"
            ),
            "witness_sources": [compiler_source, fallback_source],
        }
    return {
        "status": "missing",
        "plan_compile": {"resolved": True, "input_path": None, "source": compiler_source},
        "runtime_fallback": None,
        "reason": "compiler emits no binding and no runtime fallback binding exists",
        "witness_sources": [compiler_source, fallback_source],
    }


def adjudicate_runtime_binding_candidates(graph: dict[str, Any], *, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
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
                    "binding_disposition": "UNRESOLVED",
                    "applicability": {
                        "state": "unresolved",
                        "decision": "static",
                        "reason": "candidate does not identify exactly job/action/artifact nodes",
                    },
                    "reason": "binding candidate shape is incomplete",
                }
            )
            continue

        job_id, action_id, artifact_id = related
        job = nodes.get(job_id, {})
        action = nodes.get(action_id, {})
        artifact = nodes.get(artifact_id, {})
        action_name = str(action.get("label") or action_id.removeprefix("action:"))
        artifact_name = str(artifact.get("label") or artifact_id.removeprefix("artifact:"))
        dependency = _producer_dependency(
            job_id=job_id,
            artifact_id=artifact_id,
            nodes=nodes,
            edges_by_source=edges_by_source,
        )
        applicability = _applicability(job=job, dependency=dependency)
        witness_sources = _finding_sources(finding)
        base: dict[str, Any] = {
            "finding_id": finding.get("id"),
            "job": job_id.removeprefix("job:"),
            "action": action_name,
            "artifact": artifact_name,
            "job_maturity": job.get("maturity"),
            "dependency": dependency,
            "applicability": applicability,
        }

        if applicability["state"] == "inactive":
            results.append(
                {
                    **base,
                    "result": "SATISFIED",
                    "binding_disposition": "NOT_APPLICABLE",
                    "witness_sources": sorted(witness_sources),
                    "reason": "no runtime artifact-binding obligation is active for a non-runtime job",
                }
            )
            continue
        if applicability["state"] == "unresolved":
            results.append(
                {
                    **base,
                    "result": "INDETERMINATE",
                    "binding_disposition": "UNRESOLVED",
                    "witness_sources": sorted(witness_sources),
                    "reason": "producer-dependency applicability could not be established",
                }
            )
            continue

        fallback = _fallback_binding(
            action_id=action_id,
            artifact_id=artifact_id,
            edges_by_source=edges_by_source,
        )
        binding = _binding_witness(
            repo_root=repo_root,
            action_name=action_name,
            artifact_name=artifact_name,
            fallback=fallback,
        )
        witness_sources.update(str(item) for item in binding.get("witness_sources", []) if item)

        if binding["status"] == "indeterminate":
            results.append(
                {
                    **base,
                    "result": "INDETERMINATE",
                    "binding_disposition": "UNRESOLVED",
                    "binding": binding,
                    "witness_sources": sorted(witness_sources),
                    "reason": str(binding["reason"]),
                }
            )
            continue
        if binding["status"] == "missing":
            conditional = applicability["state"] not in {"always_when_job_selected"}
            results.append(
                {
                    **base,
                    "result": "VIOLATED",
                    "binding_disposition": "MISSING_WHEN_APPLICABLE",
                    "binding": binding,
                    "witness_sources": sorted(witness_sources),
                    "reason": (
                        "applicable producer path has no source-backed artifact binding"
                        + (" when its activation condition is met" if conditional else "")
                    ),
                }
            )
            continue

        input_path = binding.get("input_path")
        if not isinstance(input_path, str):
            results.append(
                {
                    **base,
                    "result": "INDETERMINATE",
                    "binding_disposition": "UNRESOLVED",
                    "binding": binding,
                    "witness_sources": sorted(witness_sources),
                    "reason": "resolved binding does not expose a statically checkable input path",
                }
            )
            continue

        schema = _schema_acceptance(
            action_name=action_name,
            input_path=input_path,
            action_models=action_models,
            shapes=shapes,
        )
        if isinstance(schema.get("input_model_source"), str):
            witness_sources.add(str(schema["input_model_source"]))
        if schema["status"] == "accepted":
            results.append(
                {
                    **base,
                    "result": "SATISFIED",
                    "binding_disposition": "COMPATIBLE_WHEN_APPLICABLE",
                    "binding": binding,
                    "schema": schema,
                    "witness_sources": sorted(witness_sources),
                    "reason": "source-backed binding reaches a field accepted by the registered action input model",
                }
            )
            continue
        if schema["status"] == "rejected":
            conditional = applicability["state"] not in {"always_when_job_selected"}
            results.append(
                {
                    **base,
                    "result": "VIOLATED",
                    "binding_disposition": "SCHEMA_REJECTED_WHEN_APPLICABLE",
                    "binding": binding,
                    "schema": schema,
                    "witness_sources": sorted(witness_sources),
                    "reason": (
                        "binding targets a field rejected by the registered action input model"
                        + (" when its activation condition is met" if conditional else "")
                    ),
                }
            )
            continue
        results.append(
            {
                **base,
                "result": "INDETERMINATE",
                "binding_disposition": "UNRESOLVED",
                "binding": binding,
                "schema": schema,
                "witness_sources": sorted(witness_sources),
                "reason": "binding exists but schema acceptance cannot be proven statically",
            }
        )

    counts = {result: 0 for result in sorted(RESULTS)}
    for item in results:
        counts[str(item["result"])] += 1
    return {
        "schema_version": "1.1",
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
            "applicability_instantiation": "required-for-conditional-enforcement",
            "note": (
                "Adjudication evidence only. Conditional results describe structural disposition when "
                "their predicate activates; they do not claim a specific mission activates that path."
            ),
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
        applicability = item.get("applicability", {}).get("state", "unresolved")
        print(
            f"{item['result']}: {item['finding_id']} "
            f"[{applicability}; {item.get('binding_disposition')}] — {item['reason']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Adjudicate GRAFT runtime artifact-binding findings.")
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
