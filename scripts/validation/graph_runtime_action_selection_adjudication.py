#!/usr/bin/env python3
"""Add resolver-selection witnesses to G.R.A.F.T. runtime-contract adjudication.

The binding/consumption adjudicator answers whether an artifact contract is satisfied
*if an action is used*. This layer answers the separate question of how that action
can become the resolver's selected action for its BusinessJob.

It intentionally reparses ``capability_resolver.py`` and ``job_catalog.py`` instead of
consuming the resolver-selection inventory parser. That duplicate source acquisition
is a reproducibility control: graph topology and adjudication should be capable of
disagreeing if either parser is defective.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_DIR = Path(__file__).resolve().parent
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from build_dependency_graph import build_graph  # noqa: E402
from graph_runtime_contract_consumption import adjudicate_runtime_contracts_with_consumption  # noqa: E402

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


def _assignment(tree: ast.Module, name: str) -> ast.AST | None:
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in statement.targets):
                return statement.value
        if isinstance(statement, ast.AnnAssign):
            if isinstance(statement.target, ast.Name) and statement.target.id == name:
                return statement.value
    return None


def _catalog_jobs(tree: ast.Module) -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _constructor_name(node) != "BusinessJob":
            continue
        job_key = _literal_string(_keyword(node, "job_key"))
        if not job_key:
            continue
        jobs[job_key] = {
            "candidate_actions": list(_literal_strings(_keyword(node, "candidate_actions"))),
            "maturity": _literal_string(_keyword(node, "maturity")),
            "credential_policy": _literal_string(_keyword(node, "credential_policy")),
        }
    return jobs


def _resolver_preferences(tree: ast.Module) -> dict[str, list[str]]:
    value = _assignment(tree, "_ACTION_PREFERENCE")
    if not isinstance(value, ast.Dict):
        return {}
    result: dict[str, list[str]] = {}
    for key_node, value_node in zip(value.keys, value.values, strict=True):
        key = _literal_string(key_node)
        actions = list(_literal_strings(value_node))
        if key and actions:
            result[key] = actions
    return result


def _dict_fields(node: ast.AST) -> dict[str, str]:
    if not isinstance(node, ast.Dict):
        return {}
    result: dict[str, str] = {}
    for key_node, value_node in zip(node.keys, node.values, strict=True):
        key = _literal_string(key_node)
        value = _literal_string(value_node)
        if key and value:
            result[key] = value
    return result


def _action_hints(tree: ast.Module, name: str) -> dict[str, dict[str, str]]:
    value = _assignment(tree, name)
    if not isinstance(value, ast.Dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for key_node, value_node in zip(value.keys, value.values, strict=True):
        key = _literal_string(key_node)
        fields = _dict_fields(value_node)
        if key and fields:
            result[key] = fields
    return result


def _pair_hints(tree: ast.Module, name: str) -> dict[tuple[str, str], dict[str, str]]:
    value = _assignment(tree, name)
    if not isinstance(value, ast.Dict):
        return {}
    result: dict[tuple[str, str], dict[str, str]] = {}
    for key_node, value_node in zip(value.keys, value.values, strict=True):
        if not isinstance(key_node, ast.Tuple) or len(key_node.elts) != 2:
            continue
        job_key = _literal_string(key_node.elts[0])
        action = _literal_string(key_node.elts[1])
        fields = _dict_fields(value_node)
        if job_key and action and fields:
            result[(job_key, action)] = fields
    return result


def _job_key_in_test(node: ast.AST) -> str | None:
    for item in ast.walk(node):
        if not isinstance(item, ast.Compare) or len(item.ops) != 1 or len(item.comparators) != 1:
            continue
        left = item.left
        if not (
            isinstance(item.ops[0], ast.Eq)
            and isinstance(left, ast.Attribute)
            and left.attr == "job_key"
            and isinstance(left.value, ast.Name)
            and left.value.id == "job"
        ):
            continue
        value = _literal_string(item.comparators[0])
        if value:
            return value
    return None


def _assigned_preference(statements: list[ast.stmt]) -> list[str]:
    for statement in statements:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "preference" for target in statement.targets):
            continue
        values = list(_literal_strings(statement.value))
        if values:
            return values
    return []


def _source_overrides(tree: ast.Module) -> dict[str, list[dict[str, Any]]]:
    function = next(
        (item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "resolve_jobs"),
        None,
    )
    if function is None:
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        job_key = _job_key_in_test(node.test)
        actions = _assigned_preference(node.body)
        if not job_key or not actions:
            continue
        names = sorted(
            {
                item.id
                for item in ast.walk(node.test)
                if isinstance(item, ast.Name) and item.id not in {"job", "True", "False", "None"}
            }
        )
        result.setdefault(job_key, []).append(
            {
                "predicate_names": names,
                "actions": actions,
            }
        )
    return result


def _normal_order(job: dict[str, Any], preference: list[str] | None) -> list[str]:
    candidates = [str(item) for item in job.get("candidate_actions", [])]
    ordered = list(preference or candidates)
    ordered.extend(action for action in candidates if action not in ordered)
    return ordered


def _selection_witness(
    *,
    job_key: str,
    action: str,
    jobs: dict[str, dict[str, Any]],
    preferences: dict[str, list[str]],
    action_hints: dict[str, dict[str, str]],
    job_hints: dict[tuple[str, str], dict[str, str]],
    source_hints: dict[tuple[str, str], dict[str, str]],
    overrides: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    job = jobs.get(job_key)
    resolver_source = str(RESOLVER_PATH).replace("\\", "/")
    catalog_source = str(JOB_CATALOG_PATH).replace("\\", "/")
    if job is None:
        return {
            "state": "unresolved",
            "decision": "static",
            "reason": "business job was not independently recovered from the catalog",
            "witness_sources": [resolver_source, catalog_source],
        }
    if job.get("maturity") != "runtime_bound":
        return {
            "state": "inactive",
            "decision": "static",
            "reason": "job is not runtime_bound",
            "witness_sources": [resolver_source, catalog_source],
        }

    order = _normal_order(job, preferences.get(job_key))
    if action not in order:
        return {
            "state": "not_resolver_selectable",
            "decision": "static",
            "normal_order": order,
            "reason": "action is not present in the resolver's effective normal order",
            "witness_sources": [resolver_source, catalog_source],
        }

    position = order.index(action)
    role = "primary" if position == 0 else "fallback"
    hint = job_hints.get((job_key, action)) or action_hints.get(action)
    alternate_roles: list[dict[str, Any]] = []
    for override in overrides.get(job_key, []):
        actions = [str(item) for item in override.get("actions", [])]
        row: dict[str, Any] = {
            "predicate_names": list(override.get("predicate_names", [])),
            "included": action in actions,
        }
        if action in actions:
            override_position = actions.index(action)
            row["position"] = override_position
            row["role"] = "primary" if override_position == 0 else "fallback"
            source_hint = source_hints.get((job_key, action))
            if source_hint:
                row["connection_hint"] = source_hint
        alternate_roles.append(row)

    requirements = ["consumer job is selected", "action evaluates ready under resolver gates"]
    if position > 0:
        requirements.append("all prior resolver actions are rejected or unready")
    if hint:
        requirements.append("required connection is available")

    witness: dict[str, Any] = {
        "state": "conditional_on_resolver_selection",
        "decision": "requires_instantiated_resolver_state",
        "normal_position": position,
        "normal_role": role,
        "normal_order": order,
        "prior_actions": order[:position],
        "catalog_declared": action in set(job.get("candidate_actions", [])),
        "requirements": requirements,
        "reason": (
            "resolve_jobs evaluates actions in order and selects the first ready action; "
            "mission charter, forbidden actions, registration/manifests, connections, and source constraints "
            "can change which action is selected"
        ),
        "witness_sources": [resolver_source, catalog_source],
    }
    if hint:
        witness["connection_hint"] = hint
    if alternate_roles:
        witness["source_overrides"] = alternate_roles
    return witness


def _resolver_catalog_drifts(
    *,
    jobs: dict[str, dict[str, Any]],
    preferences: dict[str, list[str]],
) -> list[dict[str, Any]]:
    resolver_source = str(RESOLVER_PATH).replace("\\", "/")
    catalog_source = str(JOB_CATALOG_PATH).replace("\\", "/")
    findings: list[dict[str, Any]] = []
    for job_key, job in sorted(jobs.items()):
        candidates = set(str(item) for item in job.get("candidate_actions", []))
        order = _normal_order(job, preferences.get(job_key))
        for position, action in enumerate(order):
            if action in candidates:
                continue
            findings.append(
                {
                    "id": f"resolver-catalog-action-drift:{job_key}:{action}",
                    "classification": "resolver_catalog_action_drift",
                    "status": "confirmed_source_drift",
                    "job": job_key,
                    "action": action,
                    "normal_position": position,
                    "normal_role": "primary" if position == 0 else "fallback",
                    "witness_sources": [resolver_source, catalog_source],
                    "reason": "resolver effective action order contains an action absent from BusinessJob candidate_actions",
                }
            )
    return findings


def adjudicate_runtime_action_selection(
    graph: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Attach independent resolver-selection applicability to final binding results."""

    binding_report = adjudicate_runtime_contracts_with_consumption(graph, repo_root=repo_root)
    resolver_tree = _parse(repo_root / RESOLVER_PATH)
    catalog_tree = _parse(repo_root / JOB_CATALOG_PATH)
    jobs = _catalog_jobs(catalog_tree)
    preferences = _resolver_preferences(resolver_tree)
    action_hints = _action_hints(resolver_tree, "_CONNECTION_HINTS")
    job_hints = _pair_hints(resolver_tree, "_JOB_CONNECTION_HINTS")
    source_hints = _pair_hints(resolver_tree, "_SOURCE_CONNECTION_HINTS")
    overrides = _source_overrides(resolver_tree)

    results: list[dict[str, Any]] = []
    for item in binding_report.get("results", []):
        row = dict(item)
        job_key = str(row.get("job") or "")
        action = str(row.get("action") or "")
        row["action_selection"] = _selection_witness(
            job_key=job_key,
            action=action,
            jobs=jobs,
            preferences=preferences,
            action_hints=action_hints,
            job_hints=job_hints,
            source_hints=source_hints,
            overrides=overrides,
        )
        results.append(row)

    primary_violations = sum(
        1
        for item in results
        if item.get("result") == "VIOLATED" and item.get("action_selection", {}).get("normal_role") == "primary"
    )
    fallback_violations = sum(
        1
        for item in results
        if item.get("result") == "VIOLATED" and item.get("action_selection", {}).get("normal_role") == "fallback"
    )
    unresolved_selection = sum(
        1
        for item in results
        if item.get("action_selection", {}).get("state") in {"unresolved", "not_resolver_selectable"}
    )
    drifts = _resolver_catalog_drifts(jobs=jobs, preferences=preferences)

    return {
        "schema_version": "1.0",
        "scope": "runtime-artifact-binding-plus-action-selection-applicability",
        "graph_schema_version": graph.get("schema_version"),
        "binding_report_schema_version": binding_report.get("schema_version"),
        "results": sorted(results, key=lambda item: str(item.get("finding_id"))),
        "resolver_catalog_findings": drifts,
        "metrics": {
            **dict(binding_report.get("metrics", {})),
            "violated_primary_action_count": primary_violations,
            "violated_fallback_action_count": fallback_violations,
            "unresolved_action_selection_count": unresolved_selection,
            "resolver_catalog_drift_count": len(drifts),
        },
        "policy": {
            "enforcement": "disabled",
            "action_selection_instantiation": "required-for-enforcement",
            "note": (
                "A structural binding result is conditioned on the resolver actually selecting that action. "
                "Primary/fallback order and static readiness predicates do not prove a specific mission selection."
            ),
        },
    }


def _print_human(report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    print(
        "GRAFT action-selection adjudication: "
        f"{metrics['candidate_count']} binding candidate(s), "
        f"{metrics['violated_primary_action_count']} primary-action violation(s), "
        f"{metrics['violated_fallback_action_count']} fallback-action violation(s), "
        f"{metrics['resolver_catalog_drift_count']} resolver/catalog drift(s)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Adjudicate GRAFT runtime action-selection applicability.")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    report = adjudicate_runtime_action_selection(build_graph())
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
    sys.exit(main())
