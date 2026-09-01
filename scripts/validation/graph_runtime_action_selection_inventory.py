#!/usr/bin/env python3
"""Derive source-backed runtime action-selection topology for G.R.A.F.T.

This inventory is intentionally independent from the runtime-contract catalog
inventory. It reconstructs the resolver's own action ordering and readiness surface
from ``capability_resolver.py`` and compares that authority with the BusinessJob
catalog without collapsing the two sources into one parser.

The result distinguishes catalog candidacy from resolver selectability. A resolver
selection node represents one job/action path and records normal ordering, fallback
position, source-specific overrides, and connection predicates that are statically
recoverable. It never claims that a particular mission actually selected the path.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

RESOLVER_PATH = Path("backend/services/mission_composition/capability_resolver.py")
JOB_CATALOG_PATH = Path("backend/services/mission_composition/job_catalog.py")


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
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        result: list[str] = []
        for item in node.elts:
            value = _literal_string(item)
            if value is None:
                return ()
            result.append(value)
        return tuple(result)
    value = _literal_string(node)
    return (value,) if value is not None else ()


def _module_assignment(tree: ast.Module, name: str) -> ast.AST | None:
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in statement.targets):
                return statement.value
        elif isinstance(statement, ast.AnnAssign):
            if isinstance(statement.target, ast.Name) and statement.target.id == name:
                return statement.value
    return None


def _job_records(tree: ast.Module) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _constructor_name(node) != "BusinessJob":
            continue
        job_key = _literal_string(_keyword(node, "job_key"))
        if not job_key:
            continue
        records[job_key] = {
            "candidate_actions": _literal_strings(_keyword(node, "candidate_actions")),
            "maturity": _literal_string(_keyword(node, "maturity")),
            "credential_policy": _literal_string(_keyword(node, "credential_policy")),
        }
    return records


def _preferences(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    value = _module_assignment(tree, "_ACTION_PREFERENCE")
    if not isinstance(value, ast.Dict):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for key_node, value_node in zip(value.keys, value.values, strict=True):
        key = _literal_string(key_node)
        actions = _literal_strings(value_node)
        if key and actions:
            result[key] = actions
    return result


def _dict_string_fields(node: ast.AST) -> dict[str, str]:
    if not isinstance(node, ast.Dict):
        return {}
    result: dict[str, str] = {}
    for key_node, value_node in zip(node.keys, node.values, strict=True):
        key = _literal_string(key_node)
        value = _literal_string(value_node)
        if key and value:
            result[key] = value
    return result


def _action_hint_map(tree: ast.Module, name: str) -> dict[str, dict[str, str]]:
    value = _module_assignment(tree, name)
    if not isinstance(value, ast.Dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for key_node, value_node in zip(value.keys, value.values, strict=True):
        key = _literal_string(key_node)
        fields = _dict_string_fields(value_node)
        if key and fields:
            result[key] = fields
    return result


def _job_action_hint_map(tree: ast.Module, name: str) -> dict[tuple[str, str], dict[str, str]]:
    value = _module_assignment(tree, name)
    if not isinstance(value, ast.Dict):
        return {}
    result: dict[tuple[str, str], dict[str, str]] = {}
    for key_node, value_node in zip(value.keys, value.values, strict=True):
        if not isinstance(key_node, ast.Tuple) or len(key_node.elts) != 2:
            continue
        job_key = _literal_string(key_node.elts[0])
        action = _literal_string(key_node.elts[1])
        fields = _dict_string_fields(value_node)
        if job_key and action and fields:
            result[(job_key, action)] = fields
    return result


def _job_key_from_test(node: ast.AST) -> str | None:
    for item in ast.walk(node):
        if not isinstance(item, ast.Compare) or len(item.ops) != 1 or len(item.comparators) != 1:
            continue
        if not isinstance(item.ops[0], ast.Eq):
            continue
        left = item.left
        if not (
            isinstance(left, ast.Attribute)
            and left.attr == "job_key"
            and isinstance(left.value, ast.Name)
            and left.value.id == "job"
        ):
            continue
        value = _literal_string(item.comparators[0])
        if value:
            return value
    return None


def _predicate_names(node: ast.AST) -> tuple[str, ...]:
    ignored = {"job", "True", "False", "None"}
    return tuple(sorted({item.id for item in ast.walk(node) if isinstance(item, ast.Name) and item.id not in ignored}))


def _assigned_sequence(statements: list[ast.stmt], name: str) -> tuple[str, ...]:
    for statement in statements:
        if isinstance(statement, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in statement.targets):
                values = _literal_strings(statement.value)
                if values:
                    return values
        elif isinstance(statement, ast.AnnAssign):
            if isinstance(statement.target, ast.Name) and statement.target.id == name:
                values = _literal_strings(statement.value)
                if values:
                    return values
    return ()


def _source_overrides(tree: ast.Module) -> list[dict[str, Any]]:
    function = next(
        (item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "resolve_jobs"),
        None,
    )
    if function is None:
        return []
    result: list[dict[str, Any]] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        job_key = _job_key_from_test(node.test)
        actions = _assigned_sequence(node.body, "preference")
        if not job_key or not actions:
            continue
        predicates = tuple(name for name in _predicate_names(node.test) if name != "job_key")
        result.append(
            {
                "job_key": job_key,
                "predicate_names": list(predicates),
                "actions": list(actions),
            }
        )
    return sorted(result, key=lambda item: (str(item["job_key"]), tuple(item["actions"])))


def _readiness_states(tree: ast.Module) -> list[str]:
    function = next(
        (item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "evaluate_action_candidate"),
        None,
    )
    if function is None:
        return []
    states: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or _constructor_name(node) != "AbilitySelection":
            continue
        value = _literal_string(_keyword(node, "readiness"))
        if value:
            states.add(value)
    return sorted(states)


def _normal_hint(
    *,
    job_key: str,
    action: str,
    action_hints: dict[str, dict[str, str]],
    job_hints: dict[tuple[str, str], dict[str, str]],
) -> dict[str, str] | None:
    return job_hints.get((job_key, action)) or action_hints.get(action)


def _selection_role(position: int) -> str:
    return "primary" if position == 0 else "fallback"


def collect_runtime_action_selection_inventory(repo_root: Path) -> dict[str, Any]:
    """Return resolver selection nodes/edges/findings without claiming mission activation."""

    resolver_path = repo_root / RESOLVER_PATH
    catalog_path = repo_root / JOB_CATALOG_PATH
    resolver_tree = _parse(resolver_path)
    catalog_tree = _parse(catalog_path)
    jobs = _job_records(catalog_tree)
    preferences = _preferences(resolver_tree)
    action_hints = _action_hint_map(resolver_tree, "_CONNECTION_HINTS")
    job_hints = _job_action_hint_map(resolver_tree, "_JOB_CONNECTION_HINTS")
    source_hints = _job_action_hint_map(resolver_tree, "_SOURCE_CONNECTION_HINTS")
    overrides = _source_overrides(resolver_tree)
    readiness_states = _readiness_states(resolver_tree)

    resolver_source = str(RESOLVER_PATH).replace("\\", "/")
    catalog_source = str(JOB_CATALOG_PATH).replace("\\", "/")
    global_catalog_actions = {
        action
        for job in jobs.values()
        for action in job.get("candidate_actions", ())
        if isinstance(action, str) and action
    }

    action_nodes: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    resolver_actions: set[str] = set()
    resolver_only_pairs: list[tuple[str, str]] = []

    override_by_job: dict[str, list[dict[str, Any]]] = {}
    for override in overrides:
        override_by_job.setdefault(str(override["job_key"]), []).append(override)

    for job_key, record in sorted(jobs.items()):
        candidates = tuple(str(item) for item in record.get("candidate_actions", ()) if item)
        explicit_preference = preferences.get(job_key, ())
        normal_order = list(explicit_preference or candidates)
        normal_order.extend(action for action in candidates if action not in normal_order)

        for position, action in enumerate(normal_order):
            resolver_actions.add(action)
            catalog_declared = action in candidates
            if not catalog_declared:
                resolver_only_pairs.append((job_key, action))
            hint = _normal_hint(
                job_key=job_key,
                action=action,
                action_hints=action_hints,
                job_hints=job_hints,
            )
            alternate_roles: list[dict[str, Any]] = []
            for override in override_by_job.get(job_key, []):
                override_actions = [str(item) for item in override.get("actions", [])]
                predicate_names = list(override.get("predicate_names", []))
                if action in override_actions:
                    override_position = override_actions.index(action)
                    source_hint = source_hints.get((job_key, action))
                    alternate_roles.append(
                        {
                            "predicate_names": predicate_names,
                            "position": override_position,
                            "role": _selection_role(override_position),
                            "included": True,
                            "connection_hint": source_hint,
                        }
                    )
                else:
                    alternate_roles.append(
                        {
                            "predicate_names": predicate_names,
                            "included": False,
                        }
                    )

            selection_id = f"selection:{job_key}:{action}"
            node: dict[str, Any] = {
                "id": selection_id,
                "type": "runtime_action_selection",
                "source": resolver_source,
                "label": f"{job_key} → {action}",
                "job_key": job_key,
                "action": action,
                "normal_position": position,
                "normal_role": _selection_role(position),
                "prior_actions": normal_order[:position],
                "catalog_declared": catalog_declared,
                "explicit_preference": action in explicit_preference,
                "job_maturity": record.get("maturity"),
                "job_credential_policy": record.get("credential_policy"),
                "readiness_states": readiness_states,
                "requires_instantiated_resolver_state": True,
            }
            if hint:
                node["connection_hint"] = hint
            if alternate_roles:
                node["source_overrides"] = alternate_roles
            nodes.append(node)
            edges.extend(
                [
                    {
                        "from": f"job:{job_key}",
                        "to": selection_id,
                        "type": "resolver_selection",
                        "evidence": resolver_source,
                    },
                    {
                        "from": selection_id,
                        "to": f"action:{action}",
                        "type": "selects_action",
                        "evidence": resolver_source,
                    },
                    {
                        "from": selection_id,
                        "to": "py:backend.services.mission_composition.capability_resolver",
                        "type": "resolved_in",
                        "evidence": resolver_source,
                    },
                ]
            )

            if not catalog_declared:
                findings.append(
                    {
                        "id": f"resolver-catalog-action-drift:{job_key}:{action}",
                        "category": "runtime-action-selection",
                        "severity": "high",
                        "summary": (
                            f"Resolver can evaluate/select {action} for {job_key}, but the BusinessJob "
                            "catalog does not declare that action as a candidate."
                        ),
                        "evidence": [resolver_source, catalog_source],
                        "related_nodes": [f"job:{job_key}", selection_id, f"action:{action}"],
                        "blocking": False,
                        "classification": "resolver_catalog_action_drift",
                    }
                )

    for job_key, actions in sorted(preferences.items()):
        if job_key in jobs:
            continue
        findings.append(
            {
                "id": f"resolver-unknown-job:{job_key}",
                "category": "runtime-action-selection",
                "severity": "high",
                "summary": f"Resolver preference references job {job_key}, which is absent from the BusinessJob catalog.",
                "evidence": [resolver_source, catalog_source],
                "related_nodes": [],
                "blocking": True,
                "classification": "resolver_unknown_job",
                "resolver_actions": list(actions),
            }
        )

    for action in sorted(resolver_actions - global_catalog_actions):
        action_nodes.append(
            {
                "id": f"action:{action}",
                "type": "runtime_action",
                "source": resolver_source,
                "label": action,
                "declared_in": resolver_source,
                "implementation_sources": [],
                "resolver_only_global": True,
            }
        )

    return {
        "action_nodes": action_nodes,
        "nodes": sorted(nodes, key=lambda item: str(item["id"])),
        "edges": sorted(
            edges,
            key=lambda item: (str(item["from"]), str(item["to"]), str(item["type"])),
        ),
        "findings": sorted(findings, key=lambda item: str(item["id"])),
        "metrics": {
            "job_count": len(jobs),
            "selection_count": len(nodes),
            "primary_count": sum(1 for node in nodes if node.get("normal_role") == "primary"),
            "fallback_count": sum(1 for node in nodes if node.get("normal_role") == "fallback"),
            "resolver_only_pair_count": len(resolver_only_pairs),
            "resolver_only_global_action_count": len(resolver_actions - global_catalog_actions),
            "connection_constrained_selection_count": sum(1 for node in nodes if node.get("connection_hint")),
            "source_override_count": len(overrides),
            "readiness_state_count": len(readiness_states),
        },
    }
