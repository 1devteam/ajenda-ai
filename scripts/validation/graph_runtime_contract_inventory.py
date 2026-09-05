#!/usr/bin/env python3
"""Derive source-backed runtime contract semantics for the canonical graph.

This inventory is intentionally static and dependency-light so the architecture graph
can be generated before application dependencies are installed. It parses the
canonical mission-composition BusinessJob catalog and runtime binding source to expose
semantic topology that module imports alone cannot express:

- business jobs;
- produced runtime artifacts;
- externally supplied job inputs;
- candidate runtime actions and their discoverable handler modules;
- typed hard, conditional, and optional job dependencies;
- runtime artifact-to-action binding paths.

Graph direction follows the canonical consumer -> dependency convention. A job
therefore points to inputs/actions/dependency jobs, while an artifact points to the
job(s) that produce it and an action points to artifacts bound into its input.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from typing import Any

JOB_CATALOG_PATH = Path("backend/services/mission_composition/job_catalog.py")
ACTION_INPUT_SEED_PATH = Path("backend/services/mission_composition/action_inputs.py")
RUNTIME_BINDING_PATH = Path("backend/services/tools/mission_input_binding.py")
ACTION_IMPLEMENTATION_ROOT = Path("backend/services/tools")
ALLOWED_DEPENDENCY_KINDS = frozenset({"hard", "conditional", "optional"})


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
    if node is None:
        return ()
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        values: list[str] = []
        for item in node.elts:
            value = _literal_string(item)
            if value is None:
                return ()
            values.append(value)
        return tuple(values)
    value = _literal_string(node)
    return (value,) if value is not None else ()


def _module_for_path(repo_root: Path, path: Path) -> str:
    rel = path.relative_to(repo_root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _dependency(call: ast.Call) -> dict[str, Any] | None:
    if _constructor_name(call) != "JobDependency":
        return None
    job_key = _literal_string(_keyword(call, "job_key"))
    if not job_key:
        return None
    kind = _literal_string(_keyword(call, "kind")) or "hard"
    return {
        "job_key": job_key,
        "kind": kind,
        "required_when_missing": _literal_strings(_keyword(call, "required_when_missing")),
        "satisfied_by": _literal_strings(_keyword(call, "satisfied_by")),
    }


def _dependencies(node: ast.AST | None) -> tuple[dict[str, Any], ...]:
    if not isinstance(node, (ast.Tuple, ast.List)):
        return ()
    result: list[dict[str, Any]] = []
    for item in node.elts:
        if not isinstance(item, ast.Call):
            continue
        dependency = _dependency(item)
        if dependency is not None:
            result.append(dependency)
    return tuple(result)


def _job_records(tree: ast.Module) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _constructor_name(node) != "BusinessJob":
            continue
        job_key = _literal_string(_keyword(node, "job_key"))
        if not job_key:
            continue
        jobs.append(
            {
                "job_key": job_key,
                "display_name": _literal_string(_keyword(node, "display_name")) or job_key,
                "vertical_role": _literal_string(_keyword(node, "vertical_role")),
                "risk_level": _literal_string(_keyword(node, "risk_level")),
                "maturity": _literal_string(_keyword(node, "maturity")),
                "credential_policy": _literal_string(_keyword(node, "credential_policy")),
                "approval_policy": _literal_string(_keyword(node, "approval_policy")),
                "required_inputs": _literal_strings(_keyword(node, "required_inputs")),
                "produced_outputs": _literal_strings(_keyword(node, "produced_outputs")),
                "candidate_actions": _literal_strings(_keyword(node, "candidate_actions")),
                "dependencies": _dependencies(_keyword(node, "dependencies")),
                "legacy_dependencies": _literal_strings(_keyword(node, "depends_on_jobs")),
            }
        )
    return sorted(jobs, key=lambda item: str(item["job_key"]))


def _action_sources(repo_root: Path, actions: set[str]) -> dict[str, tuple[str, ...]]:
    root = repo_root / ACTION_IMPLEMENTATION_ROOT
    matches: dict[str, set[str]] = defaultdict(set)
    if not root.exists() or not actions:
        return {}
    for path in sorted(root.rglob("*.py")):
        try:
            tree = _parse(path)
        except (OSError, SyntaxError):
            continue
        literals = {
            item.value
            for item in ast.walk(tree)
            if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value in actions
        }
        if not literals:
            continue
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        for action in literals:
            matches[action].add(rel)
    return {action: tuple(sorted(sources)) for action, sources in matches.items()}


def _action_names_from_test(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for item in ast.walk(node):
        if not isinstance(item, ast.Compare) or len(item.ops) != 1 or len(item.comparators) != 1:
            continue
        if not isinstance(item.left, ast.Name) or item.left.id != "action_name":
            continue
        values = _literal_strings(item.comparators[0])
        if isinstance(item.ops[0], ast.Eq) and len(values) == 1:
            names.update(values)
        elif isinstance(item.ops[0], ast.In):
            names.update(values)
    return names


def _dependency_hints_from_test(node: ast.AST) -> set[str]:
    hints: set[str] = set()
    for item in ast.walk(node):
        if not isinstance(item, ast.Compare) or len(item.ops) != 1 or len(item.comparators) != 1:
            continue
        if not isinstance(item.ops[0], ast.In):
            continue
        value = _literal_string(item.left)
        target = item.comparators[0]
        if value and isinstance(target, ast.Name) and target.id == "dep":
            hints.add(value)
    return hints


def _binding_append(call: ast.Call) -> dict[str, str] | None:
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "append":
        return None
    if not isinstance(call.func.value, ast.Name) or call.func.value.id != "specs":
        return None
    if len(call.args) != 1 or not isinstance(call.args[0], ast.Dict):
        return None
    raw: dict[str, str] = {}
    for key_node, value_node in zip(call.args[0].keys, call.args[0].values, strict=True):
        key = _literal_string(key_node)
        value = _literal_string(value_node)
        if key and value:
            raw[key] = value
    output_path = raw.get("output_path")
    input_path = raw.get("input_path")
    if not output_path or not input_path:
        return None
    return {"output_path": output_path, "input_path": input_path}


def _artifact_from_output_path(path: str) -> str | None:
    raw = path.strip()
    if not raw.startswith("$."):
        return None
    first = raw[2:].split(".", 1)[0]
    first = first.split("[", 1)[0].strip()
    return first or None


def _binding_specs(tree: ast.Module) -> list[dict[str, Any]]:
    function = next(
        (
            item
            for item in tree.body
            if isinstance(item, ast.FunctionDef) and item.name == "default_bindings_for_action"
        ),
        None,
    )
    if function is None:
        return []

    result: list[dict[str, Any]] = []

    def visit(
        statements: list[ast.stmt],
        *,
        action_context: set[str],
        dependency_context: set[str],
    ) -> None:
        for statement in statements:
            if isinstance(statement, ast.If):
                local_actions = _action_names_from_test(statement.test)
                body_actions = local_actions or action_context
                body_hints = dependency_context | _dependency_hints_from_test(statement.test)
                visit(statement.body, action_context=body_actions, dependency_context=body_hints)
                visit(
                    statement.orelse,
                    action_context=action_context,
                    dependency_context=dependency_context,
                )
                continue
            if isinstance(statement, (ast.For, ast.While)):
                visit(
                    statement.body,
                    action_context=action_context,
                    dependency_context=dependency_context,
                )
                visit(
                    statement.orelse,
                    action_context=action_context,
                    dependency_context=dependency_context,
                )
                continue
            for item in ast.walk(statement):
                if not isinstance(item, ast.Call):
                    continue
                binding = _binding_append(item)
                if binding is None or not action_context:
                    continue
                artifact = _artifact_from_output_path(binding["output_path"])
                if artifact is None:
                    continue
                for action_name in sorted(action_context):
                    result.append(
                        {
                            "action_name": action_name,
                            "artifact": artifact,
                            "output_path": binding["output_path"],
                            "input_path": binding["input_path"],
                            "dependency_hints": sorted(dependency_context),
                        }
                    )

    visit(function.body, action_context=set(), dependency_context=set())
    unique: dict[tuple[str, str, str, str, tuple[str, ...]], dict[str, Any]] = {}
    for item in result:
        key = (
            str(item["action_name"]),
            str(item["artifact"]),
            str(item["output_path"]),
            str(item["input_path"]),
            tuple(str(value) for value in item["dependency_hints"]),
        )
        unique[key] = item
    return [unique[key] for key in sorted(unique)]


def _actions_seeded_in_source(tree: ast.Module, actions: set[str]) -> set[str]:
    return {
        item.value
        for item in ast.walk(tree)
        if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value in actions
    }


def collect_runtime_contract_inventory(repo_root: Path) -> dict[str, Any]:
    """Return nodes, edges, and validation findings for canonical job contracts."""

    catalog = repo_root / JOB_CATALOG_PATH
    tree = _parse(catalog)
    jobs = _job_records(tree)
    catalog_source = str(JOB_CATALOG_PATH).replace("\\", "/")

    by_key: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for job in jobs:
        key = str(job["job_key"])
        if key in by_key:
            duplicates.add(key)
        by_key[key] = job
    if duplicates:
        raise ValueError(f"BusinessJob catalog defines duplicate job keys: {', '.join(sorted(duplicates))}")

    produced_outputs = {
        output for job in jobs for output in job["produced_outputs"] if isinstance(output, str) and output
    }
    actions = {action for job in jobs for action in job["candidate_actions"] if isinstance(action, str) and action}
    action_sources = _action_sources(repo_root, actions)
    binding_source = str(RUNTIME_BINDING_PATH).replace("\\", "/")
    binding_specs = _binding_specs(_parse(repo_root / RUNTIME_BINDING_PATH))
    seed_source = str(ACTION_INPUT_SEED_PATH).replace("\\", "/")
    seeded_actions = _actions_seeded_in_source(_parse(repo_root / ACTION_INPUT_SEED_PATH), actions)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for job in jobs:
        key = str(job["job_key"])
        node = {
            "id": f"job:{key}",
            "type": "business_job",
            "source": catalog_source,
            "label": str(job["display_name"]),
            "job_key": key,
        }
        for field in ("vertical_role", "risk_level", "maturity", "credential_policy", "approval_policy"):
            if job.get(field):
                node[field] = job[field]
        nodes.append(node)
        edges.append(
            {
                "from": f"job:{key}",
                "to": "py:backend.services.mission_composition.job_catalog",
                "type": "declared_in",
                "evidence": catalog_source,
            }
        )

    for artifact in sorted(produced_outputs):
        producers = sorted(str(job["job_key"]) for job in jobs if artifact in job["produced_outputs"])
        nodes.append(
            {
                "id": f"artifact:{artifact}",
                "type": "runtime_artifact",
                "source": catalog_source,
                "label": artifact,
                "producers": producers,
            }
        )
        for producer in producers:
            edges.append(
                {
                    "from": f"artifact:{artifact}",
                    "to": f"job:{producer}",
                    "type": "produced_by",
                    "evidence": catalog_source,
                }
            )

    external_inputs = sorted(
        {input_key for job in jobs for input_key in job["required_inputs"] if input_key not in produced_outputs}
    )
    for input_key in external_inputs:
        nodes.append(
            {
                "id": f"input:{input_key}",
                "type": "runtime_input",
                "source": catalog_source,
                "label": input_key,
            }
        )

    for action in sorted(actions):
        sources = action_sources.get(action, ())
        node: dict[str, Any] = {
            "id": f"action:{action}",
            "type": "runtime_action",
            "label": action,
            "declared_in": catalog_source,
            "implementation_sources": list(sources),
        }
        if len(sources) == 1:
            node["source"] = sources[0]
        else:
            node["source"] = catalog_source
        nodes.append(node)
        for source in sources:
            edges.append(
                {
                    "from": f"action:{action}",
                    "to": f"py:{_module_for_path(repo_root, repo_root / source)}",
                    "type": "implemented_in",
                    "evidence": source,
                }
            )
        if action in seeded_actions:
            edges.append(
                {
                    "from": f"action:{action}",
                    "to": "py:backend.services.mission_composition.action_inputs",
                    "type": "seeded_by",
                    "evidence": seed_source,
                }
            )

    binding_artifacts: dict[str, set[str]] = defaultdict(set)
    for spec in binding_specs:
        action = str(spec["action_name"])
        artifact = str(spec["artifact"])
        if action not in actions or artifact not in produced_outputs:
            continue
        binding_artifacts[action].add(artifact)
        edge: dict[str, Any] = {
            "from": f"action:{action}",
            "to": f"artifact:{artifact}",
            "type": "binds_artifact",
            "evidence": binding_source,
            "output_path": spec["output_path"],
            "input_path": spec["input_path"],
        }
        if spec["dependency_hints"]:
            edge["dependency_hints"] = spec["dependency_hints"]
        edges.append(edge)

    for job in jobs:
        key = str(job["job_key"])
        required_artifacts = {input_key for input_key in job["required_inputs"] if input_key in produced_outputs}
        for input_key in job["required_inputs"]:
            if input_key in produced_outputs:
                target = f"artifact:{input_key}"
                edge_type = "requires_artifact"
            else:
                target = f"input:{input_key}"
                edge_type = "requires_input"
            edges.append(
                {
                    "from": f"job:{key}",
                    "to": target,
                    "type": edge_type,
                    "evidence": catalog_source,
                }
            )

        for action in job["candidate_actions"]:
            edges.append(
                {
                    "from": f"job:{key}",
                    "to": f"action:{action}",
                    "type": "candidate_action",
                    "evidence": catalog_source,
                }
            )
            # Catalog-only jobs are intentionally not runtime-selectable. Their
            # unimplemented artifact bindings are product backlog, not runtime
            # contract violations, and must not inflate runtime proof scope.
            if str(job.get("maturity") or "") == "catalog_only":
                continue
            missing_bindings = sorted(required_artifacts - binding_artifacts.get(action, set()))
            for artifact in missing_bindings:
                findings.append(
                    {
                        "id": f"runtime-binding-gap:{key}:{action}:{artifact}",
                        "category": "runtime-contract",
                        "severity": "high",
                        "summary": (
                            f"Business job {key} requires artifact {artifact}, but candidate action {action} "
                            "has no source-derived runtime binding for that artifact."
                        ),
                        "evidence": [catalog_source, binding_source],
                        "related_nodes": [f"job:{key}", f"action:{action}", f"artifact:{artifact}"],
                        "blocking": False,
                        "classification": "binding_coverage_gap",
                    }
                )

        typed_targets: set[str] = set()
        for dependency in job["dependencies"]:
            target = str(dependency["job_key"])
            typed_targets.add(target)
            kind = str(dependency["kind"])
            edge = {
                "from": f"job:{key}",
                "to": f"job:{target}",
                "type": f"depends_on_{kind}",
                "evidence": catalog_source,
            }
            if dependency["required_when_missing"]:
                edge["required_when_missing"] = list(dependency["required_when_missing"])
            if dependency["satisfied_by"]:
                edge["satisfied_by"] = list(dependency["satisfied_by"])
            edges.append(edge)

            if kind not in ALLOWED_DEPENDENCY_KINDS:
                findings.append(
                    {
                        "id": f"job-dependency-kind:{key}:{target}",
                        "category": "runtime-contract",
                        "severity": "high",
                        "summary": f"Business job {key} uses unsupported dependency kind {kind}",
                        "evidence": [catalog_source],
                        "related_nodes": [f"job:{key}", f"job:{target}"],
                        "blocking": True,
                        "classification": "violation",
                    }
                )
            if target not in by_key:
                findings.append(
                    {
                        "id": f"job-dependency-target:{key}:{target}",
                        "category": "runtime-contract",
                        "severity": "high",
                        "summary": f"Business job {key} depends on undefined job {target}",
                        "evidence": [catalog_source],
                        "related_nodes": [f"job:{key}"],
                        "blocking": True,
                        "classification": "violation",
                    }
                )

        for target in job["legacy_dependencies"]:
            if target in typed_targets:
                continue
            edges.append(
                {
                    "from": f"job:{key}",
                    "to": f"job:{target}",
                    "type": "depends_on_legacy",
                    "evidence": catalog_source,
                }
            )
            if target not in by_key:
                findings.append(
                    {
                        "id": f"job-legacy-dependency-target:{key}:{target}",
                        "category": "runtime-contract",
                        "severity": "high",
                        "summary": f"Business job {key} has undefined legacy dependency {target}",
                        "evidence": [catalog_source],
                        "related_nodes": [f"job:{key}"],
                        "blocking": True,
                        "classification": "violation",
                    }
                )

    return {
        "nodes": sorted(nodes, key=lambda item: str(item["id"])),
        "edges": sorted(
            edges,
            key=lambda item: (str(item["from"]), str(item["to"]), str(item["type"])),
        ),
        "findings": sorted(findings, key=lambda item: str(item["id"])),
        "metrics": {
            "job_count": len(jobs),
            "artifact_count": len(produced_outputs),
            "external_input_count": len(external_inputs),
            "action_count": len(actions),
            "typed_dependency_count": sum(len(job["dependencies"]) for job in jobs),
            "binding_edge_count": sum(len(artifacts) for artifacts in binding_artifacts.values()),
            "binding_gap_count": sum(
                1 for finding in findings if finding.get("classification") == "binding_coverage_gap"
            ),
        },
    }
