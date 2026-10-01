#!/usr/bin/env python3
"""Validate and compare a Frontier GRAFT+ proposal without granting runtime authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_LIST_FIELDS = (
    "hypotheses",
    "candidate_paths",
    "invariants",
    "authority_boundaries",
    "experiments",
    "promotion_criteria",
)
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


def validate_frontier_spec(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if spec.get("schema_version") != 1:
        errors.append("schema_version must be 1")
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
            "grants_runtime_authority": False,
        },
        "standard_graft_plus": {
            "status": impact.get("status"),
            "changed_files": metrics.get("changed_files", impact.get("changed_files", [])),
            "impacted_nodes": metrics.get("impacted_nodes", impact.get("impacted_nodes")),
            "unmapped_files": impact.get("unmapped_changed_files", []),
            "risk_domains": impact.get("risk_domains", []),
        },
        "decision_boundary": {
            "frontier_is_not_implementation_authority": True,
            "promotion_requires_standard_graft_plus": True,
            "runtime_execution_unchanged": True,
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
        spec = _load_object(args.frontier_spec, "frontier spec")
        impact = _load_object(args.impact_report, "impact report")
        errors = validate_frontier_spec(spec)
        if errors:
            report = {"schema_version": 1, "status": "failed", "errors": errors}
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print("Frontier GRAFT+ validation: failed")
            return 1
        report = {
            "schema_version": 1,
            "status": "passed",
            "artifact_kind": "graft_plus_frontier_validation",
            "proposal_id": spec["proposal_id"],
            "errors": [],
            "authority": {"grants_runtime_authority": False, "runtime_effects": []},
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
