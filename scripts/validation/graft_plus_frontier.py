#!/usr/bin/env python3
"""Validate and compare a Frontier GRAFT+ proposal without granting runtime authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

VALIDATION_DIR = Path(__file__).resolve().parent
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from frontier_preflight import run_frontier_preflight  # noqa: E402

REQUIRED_LIST_FIELDS = (
    "hypotheses",
    "candidate_paths",
    "invariants",
    "authority_boundaries",
    "experiments",
    "promotion_criteria",
)
FRONTIER_SCHEMA_VERSION = 2
PLACEHOLDER_MARKERS = ("replace-with", "describe ", "state a ", "define ")
FORBIDDEN_AUTHORITY_TERMS = {
    "dispatch",
    "execute",
    "provider_call",
    "resolve_credentials",
    "grant_permission",
    "approve_side_effect",
    "register_handler",
}


def _load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_string_list(value: object, field: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        errors.append(f"{field} must be a non-empty list of strings")


def _validate_v2_experiments(spec: dict[str, Any], errors: list[str]) -> None:
    experiments = spec.get("experiments")
    if not isinstance(experiments, list):
        return
    ids: set[str] = set()
    for index, experiment in enumerate(experiments):
        prefix = f"experiments[{index}]"
        if not isinstance(experiment, dict):
            errors.append(f"{prefix} must be an object")
            continue
        experiment_id = experiment.get("id")
        if not isinstance(experiment_id, str) or not experiment_id.strip():
            errors.append(f"{prefix}.id must be a non-empty string")
        elif experiment_id in ids:
            errors.append(f"duplicate experiment id: {experiment_id}")
        else:
            ids.add(experiment_id)
        for field in ("success_signal", "measurement", "rollback"):
            if not isinstance(experiment.get(field), str) or not experiment[field].strip():
                errors.append(f"{prefix}.{field} must be a non-empty string")
        artifact_path = experiment.get("artifact_path")
        if not isinstance(artifact_path, str) or not artifact_path.startswith("artifacts/"):
            errors.append(f"{prefix}.artifact_path must be under artifacts/")


def validate_frontier_spec(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema_version = spec.get("schema_version")
    if schema_version not in {1, FRONTIER_SCHEMA_VERSION}:
        errors.append(f"schema_version must be 1 or {FRONTIER_SCHEMA_VERSION}")
    if spec.get("artifact_kind") != "graft_plus_frontier":
        errors.append("artifact_kind must be graft_plus_frontier")
    for field in ("proposal_id", "target_outcome", "status", "source_of_truth"):
        if not isinstance(spec.get(field), str) or not spec[field].strip():
            errors.append(f"{field} must be a non-empty string")
    if spec.get("status") not in {"draft", "experimental", "promotion_candidate", "rejected"}:
        errors.append("status must be draft, experimental, promotion_candidate, or rejected")
    for field in REQUIRED_LIST_FIELDS:
        if not isinstance(spec.get(field), list) or not spec[field]:
            errors.append(f"{field} must be a non-empty list")
    if spec.get("grants_runtime_authority") is not False:
        errors.append("grants_runtime_authority must be false")
    if spec.get("runtime_effects") not in ([], None):
        errors.append("runtime_effects must be empty; frontier artifacts are non-runtime")
    boundaries = spec.get("authority_boundaries", [])
    if isinstance(boundaries, list):
        flattened = json.dumps(boundaries, sort_keys=True).lower()
        for term in FORBIDDEN_AUTHORITY_TERMS:
            if term in flattened:
                errors.append(f"authority_boundaries may not claim runtime capability: {term}")
    if not isinstance(spec.get("rollback"), dict) or not spec["rollback"].get("kill_switch"):
        errors.append("rollback.kill_switch is required")
    if schema_version == FRONTIER_SCHEMA_VERSION:
        owner = spec.get("owner")
        if not isinstance(owner, dict):
            errors.append("owner must be an object")
        else:
            for field in ("accountable", "technical", "review"):
                if not isinstance(owner.get(field), str) or not owner[field].strip():
                    errors.append(f"owner.{field} must be a non-empty string")
        for field in ("unknowns", "expected_failure_modes"):
            _validate_string_list(spec.get(field), field, errors)
        artifact_root = spec.get("artifact_root")
        if not isinstance(artifact_root, str) or not artifact_root.startswith("artifacts/"):
            errors.append("artifact_root must be under artifacts/")
        evidence_policy = spec.get("evidence_policy")
        if not isinstance(evidence_policy, dict):
            errors.append("evidence_policy must be an object")
        else:
            _validate_string_list(
                evidence_policy.get("required_artifacts"), "evidence_policy.required_artifacts", errors
            )
            if not isinstance(evidence_policy.get("retention"), str) or not evidence_policy["retention"].strip():
                errors.append("evidence_policy.retention must be a non-empty string")
        _validate_v2_experiments(spec, errors)
        if isinstance(artifact_root, str) and artifact_root.startswith("artifacts/"):
            artifact_prefix = artifact_root.rstrip("/") + "/"
            for experiment in spec.get("experiments", []):
                if isinstance(experiment, dict) and isinstance(experiment.get("artifact_path"), str):
                    if not experiment["artifact_path"].startswith(artifact_prefix):
                        errors.append("experiment artifact_path must remain under artifact_root")
        if spec.get("status") == "promotion_candidate":
            promotion_evidence = spec.get("promotion_evidence")
            if not isinstance(promotion_evidence, dict):
                errors.append("promotion_evidence is required for promotion_candidate")
            else:
                _validate_string_list(
                    promotion_evidence.get("artifact_refs"), "promotion_evidence.artifact_refs", errors
                )
                for field in ("result_summary", "reviewer"):
                    if not isinstance(promotion_evidence.get(field), str) or not promotion_evidence[field].strip():
                        errors.append(f"promotion_evidence.{field} must be a non-empty string")
        serialized = json.dumps(spec, sort_keys=True).lower()
        for marker in PLACEHOLDER_MARKERS:
            if marker in serialized:
                errors.append(f"v2 frontier specs may not contain placeholder text: {marker.strip()}")
    return errors


def build_comparison(spec: dict[str, Any], impact: dict[str, Any]) -> dict[str, Any]:
    metrics = impact.get("metrics", {}) if isinstance(impact.get("metrics"), dict) else {}
    return {
        "schema_version": 1,
        "artifact_kind": "graft_plus_side_by_side_comparison",
        "frontier": {
            "proposal_id": spec["proposal_id"],
            "status": spec["status"],
            "target_outcome": spec["target_outcome"],
            "hypothesis_count": len(spec["hypotheses"]),
            "candidate_path_count": len(spec["candidate_paths"]),
            "experiment_count": len(spec["experiments"]),
            "experiment_ids": [item.get("id") for item in spec["experiments"] if isinstance(item, dict)],
            "artifact_root": spec.get("artifact_root"),
            "owner": spec.get("owner"),
            "grants_runtime_authority": False,
        },
        "standard_graft_plus": {
            "status": "analyzed",
            "changed_files": impact.get("changed_files", []),
            "changed_file_count": metrics.get("changed_file_count", len(impact.get("changed_files", []))),
            "changed_node_count": metrics.get("changed_node_count", len(impact.get("changed_nodes", []))),
            "impacted_test_count": metrics.get("impacted_test_count", len(impact.get("impacted_tests", []))),
            "unmapped_files": impact.get("unmapped_changed_files", []),
            "risk_domains": impact.get("risk_domains", []),
            "graph_sha256": impact.get("graph_sha256"),
        },
        "evidence_contract": {
            "required_artifacts": spec.get("evidence_policy", {}).get("required_artifacts", []),
            "retention": spec.get("evidence_policy", {}).get("retention"),
            "durable_artifact_required": spec.get("schema_version") == FRONTIER_SCHEMA_VERSION,
        },
        "decision_boundary": {
            "frontier_is_not_implementation_authority": True,
            "promotion_requires_standard_graft_plus": True,
            "runtime_execution_unchanged": True,
            "promotion_evidence_required": spec.get("status") == "promotion_candidate",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontier-spec", type=Path, required=True)
    parser.add_argument("--impact-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--comparison-output", type=Path, required=True)
    args = parser.parse_args()

    try:
        preflight = run_frontier_preflight()
        if not preflight["ok"]:
            report = {
                "schema_version": FRONTIER_SCHEMA_VERSION,
                "status": "failed",
                "artifact_kind": "graft_plus_frontier_validation",
                "errors": ["Frontier repository preflight failed"],
                "preflight": preflight,
            }
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print("Frontier GRAFT+ validation: failed preflight")
            return 1

        spec = _load_object(args.frontier_spec, "frontier spec")
        impact = _load_object(args.impact_report, "impact report")
        errors = validate_frontier_spec(spec)
        if errors:
            report = {"schema_version": 1, "status": "failed", "errors": errors}
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print("Frontier GRAFT+ validation: failed")
            return 1
        report = {
            "schema_version": FRONTIER_SCHEMA_VERSION,
            "status": "passed",
            "artifact_kind": "graft_plus_frontier_validation",
            "proposal_id": spec["proposal_id"],
            "spec_sha256": _canonical_sha256(spec),
            "artifact_root": spec.get("artifact_root"),
            "errors": [],
            "authority": {"grants_runtime_authority": False, "runtime_effects": []},
            "evidence_contract": {
                "required_artifacts": spec.get("evidence_policy", {}).get("required_artifacts", []),
                "durable_artifact_required": spec.get("schema_version") == FRONTIER_SCHEMA_VERSION,
            },
            "preflight": preflight,
        }
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.comparison_output.write_text(
            json.dumps(build_comparison(spec, impact), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print("Frontier GRAFT+ validation: passed")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Frontier GRAFT+ validation: failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
