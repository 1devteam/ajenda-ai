#!/usr/bin/env python3
"""Instantiate G.R.A.F.T. runtime-contract findings against concrete execution evidence.

Static binding/consumption findings remain unchanged. This layer decides whether a
finding is active for one plan/mission slice. Missing job identity, satisfier state,
resolver state, or required connection evidence yields INDETERMINATE. Enforcement is
explicitly disabled.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_DIR = Path(__file__).resolve().parent
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from build_dependency_graph import build_graph  # noqa: E402
from graph_runtime_action_selection_adjudication import adjudicate_runtime_action_selection  # noqa: E402

RESOLVER_PATH = Path("backend/services/mission_composition/capability_resolver.py")
RESULTS = frozenset({"SATISFIED", "VIOLATED", "INDETERMINATE"})
ACTION_STATES = frozenset({"ready", "rejected", "unready", "unknown"})


def _literal_assignment(tree: ast.Module, name: str) -> Any:
    for statement in tree.body:
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in statement.targets
        ):
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if statement.target.id == name:
                value = statement.value
        if value is not None:
            try:
                return ast.literal_eval(value)
            except (ValueError, TypeError):
                return None
    return None


def _resolver_inventory(repo_root: Path) -> dict[str, Any]:
    tree = ast.parse((repo_root / RESOLVER_PATH).read_text(encoding="utf-8"))
    preferences = _literal_assignment(tree, "_ACTION_PREFERENCE") or {}
    action_hints = _literal_assignment(tree, "_CONNECTION_HINTS") or {}
    job_hints = _literal_assignment(tree, "_JOB_CONNECTION_HINTS") or {}
    source_hints = _literal_assignment(tree, "_SOURCE_CONNECTION_HINTS") or {}
    return {
        "preferences": {str(job): [str(action) for action in actions] for job, actions in preferences.items()},
        "action_hints": {str(action): dict(hint) for action, hint in action_hints.items()},
        "job_hints": {(str(job), str(action)): dict(hint) for (job, action), hint in job_hints.items()},
        "source_hints": {(str(job), str(action)): dict(hint) for (job, action), hint in source_hints.items()},
    }


def _optional_set(context: dict[str, Any], key: str) -> set[str] | None:
    if key not in context or context[key] is None:
        return None
    value = context[key]
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list or null")
    return {str(item) for item in value}


def _selected_actions(context: dict[str, Any]) -> dict[str, str]:
    value = context.get("selected_actions") or {}
    if not isinstance(value, dict):
        raise ValueError("selected_actions must be an object")
    return {str(job): str(action) for job, action in value.items()}


def _action_states(context: dict[str, Any]) -> dict[str, dict[str, str]]:
    value = context.get("action_states") or {}
    if not isinstance(value, dict):
        raise ValueError("action_states must be an object")
    result: dict[str, dict[str, str]] = {}
    for job, states in value.items():
        if not isinstance(states, dict):
            raise ValueError("each action_states entry must be an object")
        normalized = {str(action): str(state) for action, state in states.items()}
        unknown = set(normalized.values()) - ACTION_STATES
        if unknown:
            raise ValueError(f"unsupported action states: {sorted(unknown)}")
        result[str(job)] = normalized
    return result


def _source_sha(repo_root: Path) -> str:
    if value := (os.getenv("GRAFT_SOURCE_SHA") or os.getenv("GITHUB_SHA")):
        return value
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True, timeout=5
        )
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unbound"


def _dependency_instance(row: dict[str, Any], available_inputs: set[str] | None) -> dict[str, Any]:
    applicability = row.get("applicability") or {}
    state = str(applicability.get("state") or "unresolved")
    if state == "inactive":
        return {"state": "NOT_APPLICABLE", "reason": "static runtime obligation is inactive"}
    if state == "unresolved":
        return {"state": "INDETERMINATE", "reason": "producer dependency is unresolved"}

    dependency = row.get("dependency") or {}
    dep_type = str(dependency.get("type") or "")
    if dep_type == "depends_on_hard" or state == "active":
        return {"state": "ACTIVE", "dependency_kind": "hard"}
    if dep_type == "depends_on_optional":
        return {"state": "NOT_APPLICABLE", "dependency_kind": "optional"}
    if dep_type != "depends_on_conditional" and state != "conditional":
        return {"state": "INDETERMINATE", "reason": "dependency kind is not classifiable"}
    if available_inputs is None:
        return {"state": "INDETERMINATE", "dependency_kind": "conditional", "reason": "input state is unknown"}

    required = {str(item) for item in dependency.get("required_when_missing") or []}
    satisfiers = {str(item) for item in dependency.get("satisfied_by") or []}
    matched = sorted(satisfiers & available_inputs)
    if matched:
        return {
            "state": "NOT_APPLICABLE",
            "dependency_kind": "conditional",
            "matched_satisfiers": matched,
            "reason": "accepted alternate satisfier is present",
        }
    missing = sorted(required - available_inputs)
    if required and missing:
        return {
            "state": "ACTIVE",
            "dependency_kind": "conditional",
            "missing_required_inputs": missing,
            "reason": "required input is missing and no alternate satisfier is present",
        }
    return {"state": "NOT_APPLICABLE", "dependency_kind": "conditional", "reason": "conditional input is present"}


def _connection_hint(
    inventory: dict[str, Any], context: dict[str, Any], *, job: str, action: str
) -> dict[str, str] | None:
    hint = inventory["job_hints"].get((job, action)) or inventory["action_hints"].get(action)
    source_required = _optional_set(context, "source_connection_required_jobs")
    if hint is None and source_required is not None and job in source_required:
        hint = inventory["source_hints"].get((job, action))
    return hint


def _connection_state(context: dict[str, Any], hint: dict[str, str] | None) -> str:
    if hint is None:
        return "not_required"
    integrations = _optional_set(context, "connected_integrations")
    credentials = _optional_set(context, "connected_credential_ids")
    if integrations is None and credentials is None:
        return "unknown"
    if credentials is not None and str(hint.get("credential_id")) in credentials:
        return "connected"
    if integrations is not None and str(hint.get("integration")) in integrations:
        return "connected"
    return "missing"


def _effective_action_state(
    inventory: dict[str, Any], context: dict[str, Any], *, job: str, action: str
) -> tuple[str, list[str]]:
    forbidden = _optional_set(context, "forbidden_actions")
    if forbidden is not None and action in forbidden:
        return "rejected", ["action is explicitly forbidden"]
    state = _action_states(context).get(job, {}).get(action, "unknown")
    connection = _connection_state(context, _connection_hint(inventory, context, job=job, action=action))
    if connection == "missing":
        return "rejected", ["required connection is known missing"]
    if connection == "unknown" and state == "ready":
        return "unknown", ["required connection state is unknown"]
    reasons = [f"instantiated action state is {state}"]
    if connection == "connected":
        reasons.append("required connection is established")
    return state, reasons


def _selection_instance(row: dict[str, Any], context: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    job = str(row.get("job") or "")
    target = str(row.get("action") or "")
    order = list(inventory["preferences"].get(job, []))
    if not order or target not in order:
        return {
            "state": "INDETERMINATE",
            "reason": "independent resolver preference for this target was not recovered",
            "normal_order": order,
        }

    selected = _selected_actions(context)
    if job in selected:
        action = selected[job]
        if action not in order:
            return {
                "state": "INDETERMINATE",
                "selected_action": action,
                "normal_order": order,
                "reason": "selected action conflicts with resolver order",
            }
        connection = _connection_state(context, _connection_hint(inventory, context, job=job, action=action))
        if connection in {"unknown", "missing"}:
            return {
                "state": "INDETERMINATE",
                "selected_action": action,
                "normal_order": order,
                "connection_state": connection,
                "reason": "selected action lacks consistent required-connection evidence",
            }
        return {
            "state": "SELECTED" if action == target else "NOT_APPLICABLE",
            "selected_action": action,
            "normal_order": order,
            "connection_state": connection,
            "decision": "direct_selected_action_evidence",
        }

    evidence: list[dict[str, Any]] = []
    for action in order:
        state, reasons = _effective_action_state(inventory, context, job=job, action=action)
        evidence.append({"action": action, "state": state, "reasons": reasons})
        if state == "ready":
            return {
                "state": "SELECTED" if action == target else "NOT_APPLICABLE",
                "selected_action": action,
                "normal_order": order,
                "decision": "first_ready_action",
                "evidence": evidence,
            }
        if state == "unknown":
            return {
                "state": "INDETERMINATE",
                "normal_order": order,
                "decision": "resolver_state_incomplete",
                "evidence": evidence,
                "reason": "resolver state is unknown before unique selection can be proven",
            }
    return {
        "state": "NOT_APPLICABLE",
        "selected_action": None,
        "normal_order": order,
        "decision": "no_ready_action",
        "evidence": evidence,
    }


def instantiate_runtime_contract_findings(
    graph: dict[str, Any], context: dict[str, Any], *, repo_root: Path = REPO_ROOT
) -> dict[str, Any]:
    """Instantiate all static runtime-contract findings without changing their static disposition."""

    upstream = adjudicate_runtime_action_selection(graph, repo_root=repo_root)
    inventory = _resolver_inventory(repo_root)
    selected_jobs = _optional_set(context, "selected_job_keys")
    available_inputs = _optional_set(context, "available_inputs")
    observed_actions = _optional_set(context, "observed_actions")
    results: list[dict[str, Any]] = []

    for base in upstream.get("results", []):
        row = dict(base)
        static_result = str(row.get("result") or "INDETERMINATE")
        witness: dict[str, Any] = {"unresolved_predicates": []}
        job = str(row.get("job") or "")

        if row.get("job_maturity") != "runtime_bound":
            instantiated = "SATISFIED" if static_result == "SATISFIED" else "INDETERMINATE"
            applicability = "NOT_APPLICABLE"
            witness["job_selection"] = {"state": "NOT_APPLICABLE", "reason": "job is not runtime_bound"}
        elif selected_jobs is None:
            instantiated = applicability = "INDETERMINATE"
            witness["job_selection"] = {
                "state": "INDETERMINATE",
                "reason": "selected_job_keys are absent; action observation alone does not prove job identity",
            }
            witness["unresolved_predicates"].append("business_job_selection")
            if observed_actions:
                witness["observed_actions"] = sorted(observed_actions)
        elif job not in selected_jobs:
            instantiated = "INDETERMINATE"
            applicability = "NOT_APPLICABLE"
            witness["job_selection"] = {"state": "NOT_APPLICABLE", "reason": "job is not selected"}
        else:
            witness["job_selection"] = {"state": "SELECTED"}
            dependency = _dependency_instance(row, available_inputs)
            witness["dependency_applicability"] = dependency
            if dependency["state"] == "INDETERMINATE":
                instantiated = applicability = "INDETERMINATE"
                witness["unresolved_predicates"].append("dependency_applicability")
            elif dependency["state"] == "NOT_APPLICABLE":
                instantiated = "INDETERMINATE"
                applicability = "NOT_APPLICABLE"
            else:
                selection = _selection_instance(row, context, inventory)
                witness["action_selection"] = selection
                if selection["state"] == "INDETERMINATE":
                    instantiated = applicability = "INDETERMINATE"
                    witness["unresolved_predicates"].append("resolver_action_selection")
                elif selection["state"] == "NOT_APPLICABLE":
                    instantiated = "INDETERMINATE"
                    applicability = "NOT_APPLICABLE"
                else:
                    applicability = "ACTIVE"
                    instantiated = static_result if static_result in RESULTS else "INDETERMINATE"

        row["static_result"] = static_result
        row["instantiated_result"] = instantiated
        row["instantiated_applicability"] = applicability
        row["instantiated_witness"] = witness
        row["repair_authorized"] = instantiated == "VIOLATED" and applicability == "ACTIVE"
        results.append(row)

    context_json = json.dumps(context, sort_keys=True, separators=(",", ":"))
    metrics = {
        "candidate_count": len(results),
        "instantiated_satisfied_count": sum(item["instantiated_result"] == "SATISFIED" for item in results),
        "instantiated_violated_count": sum(item["instantiated_result"] == "VIOLATED" for item in results),
        "instantiated_indeterminate_count": sum(item["instantiated_result"] == "INDETERMINATE" for item in results),
        "active_violation_count": sum(bool(item["repair_authorized"]) for item in results),
        "not_applicable_count": sum(item["instantiated_applicability"] == "NOT_APPLICABLE" for item in results),
    }
    return {
        "schema_version": "1.0",
        "scope": "runtime-contract-instantiated-applicability",
        "source_sha": _source_sha(repo_root),
        "context_sha256": hashlib.sha256(context_json.encode()).hexdigest(),
        "graph_schema_version": graph.get("schema_version"),
        "upstream_action_selection_schema_version": upstream.get("schema_version"),
        "context": context,
        "results": sorted(results, key=lambda item: str(item.get("finding_id"))),
        "metrics": metrics,
        "policy": {
            "enforcement": "disabled",
            "repair_authorization": "only ACTIVE + VIOLATED",
            "indeterminate": "non-enforceable",
            "action_name_observation_proves_job_identity": False,
        },
        "independent_witness_source": str(RESOLVER_PATH),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, help="JSON execution-slice context; omit for uninstantiated evidence")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    context: dict[str, Any] = {}
    if args.context is not None:
        loaded = json.loads(args.context.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("context JSON must contain one object")
        context = loaded
    report = instantiate_runtime_contract_findings(build_graph(), context, repo_root=REPO_ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
