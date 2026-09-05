#!/usr/bin/env python3
"""Compose graph analysis artifacts into one architecture decision manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from graph_selective_ci import build_shadow_plan

SUPPORTED_INPUT_SCHEMA_VERSIONS = frozenset({"1.0", "1.1", "1.2"})
DECISION_SCHEMA_VERSION = "1.1"


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"unable to read {label}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} root must be a JSON object")
    return payload


def _validate_schema(payload: dict[str, Any], *, label: str) -> None:
    if str(payload.get("schema_version")) not in SUPPORTED_INPUT_SCHEMA_VERSIONS:
        raise RuntimeError(f"unsupported {label} schema_version")


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _string_list(payload: dict[str, Any], field: str) -> list[str]:
    value = payload.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise RuntimeError(f"field {field!r} must be a list of non-empty strings")
    return sorted(set(value))


def _dict_list(payload: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = payload.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError(f"field {field!r} must be a list of objects")
    return value


def _ids(items: list[dict[str, Any]]) -> list[str]:
    return sorted({str(item["id"]) for item in items if item.get("id")})


def _sources(items: list[dict[str, Any]]) -> list[str]:
    return sorted({str(item["source"]) for item in items if isinstance(item.get("source"), str) and item["source"]})


def _impact_context_ids(impact: dict[str, Any]) -> set[str]:
    fields = (
        "changed_nodes",
        "upstream_consumers",
        "downstream_dependencies",
        "affected_semantic_nodes",
        "dependency_semantic_nodes",
    )
    context: set[str] = set()
    for field in fields:
        context.update(_ids(_dict_list(impact, field)))
    return context


def _relevant_semantic_only(
    completeness: dict[str, Any],
    context_ids: set[str],
) -> list[dict[str, str]]:
    relationships: list[dict[str, str]] = []
    for item in _dict_list(completeness, "semantic_reconciliation"):
        if item.get("classification") != "semantic-only":
            continue
        source = str(item.get("from", ""))
        target = str(item.get("to", ""))
        if source not in context_ids and target not in context_ids:
            continue
        relationships.append(
            {
                "from": source,
                "to": target,
                "type": str(item.get("type", "")),
                "evidence": str(item.get("evidence", "")),
            }
        )
    return sorted(
        relationships,
        key=lambda item: (item["from"], item["to"], item["type"], item["evidence"]),
    )


def _relevant_cross_boundary_cycles(
    completeness: dict[str, Any],
    context_ids: set[str],
) -> list[dict[str, Any]]:
    cycles: list[dict[str, Any]] = []
    for item in _dict_list(completeness, "static_cycles"):
        if item.get("classification") != "cross-boundary":
            continue
        raw_nodes = item.get("nodes", [])
        if not isinstance(raw_nodes, list):
            raise RuntimeError("static cycle nodes must be a list")
        nodes = sorted({str(node_id) for node_id in raw_nodes if node_id})
        if not context_ids.intersection(nodes):
            continue
        raw_boundaries = item.get("boundaries", [])
        if not isinstance(raw_boundaries, list):
            raise RuntimeError("static cycle boundaries must be a list")
        cycles.append(
            {
                "nodes": nodes,
                "boundaries": sorted({str(boundary) for boundary in raw_boundaries if boundary}),
            }
        )
    return sorted(cycles, key=lambda item: tuple(item["nodes"]))


def build_decision_manifest(
    impact: dict[str, Any],
    proof: dict[str, Any],
    completeness: dict[str, Any],
) -> dict[str, Any]:
    _validate_schema(impact, label="impact report")
    _validate_schema(proof, label="proof manifest")
    _validate_schema(completeness, label="completeness report")

    changed_files = _string_list(impact, "changed_files")
    unmapped_changed_files = _string_list(impact, "unmapped_changed_files")
    changed_nodes = _dict_list(impact, "changed_nodes")
    relevant_invariants = _dict_list(impact, "relevant_invariants")
    risk_domains = _dict_list(impact, "risk_domains")
    affected_semantic_nodes = _dict_list(impact, "affected_semantic_nodes")
    dependency_semantic_nodes = _dict_list(impact, "dependency_semantic_nodes")

    manual_review = _string_list(proof, "manual_review")
    review_gates = _string_list(proof, "review_gates")
    required_gates = _string_list(proof, "required_gates")
    required_tests = _string_list(proof, "required_tests")
    selected_bundles = _dict_list(proof, "selected_bundles")

    integrity = completeness.get("integrity")
    if not isinstance(integrity, dict):
        raise RuntimeError("completeness report integrity must be an object")

    blocking_reasons: list[str] = []
    review_reasons: list[str] = []
    proof_plan: dict[str, Any] | None = None
    try:
        proof_plan = build_shadow_plan(proof)
    except RuntimeError as exc:
        blocking_reasons.append(f"proof manifest validation failed: {exc}")

    if integrity.get("pass") is not True:
        blockers = integrity.get("unacknowledged_blocking_findings", [])
        suffix = f": {', '.join(str(item) for item in blockers)}" if blockers else ""
        blocking_reasons.append(f"canonical graph completeness integrity failed{suffix}")

    review_reasons.extend(manual_review)
    review_reasons.extend(f"review-only gate required: {gate}" for gate in review_gates)

    if blocking_reasons:
        disposition = "blocked"
    elif review_reasons:
        disposition = "review-required"
    else:
        disposition = "clear"

    context_ids = _impact_context_ids(impact)
    semantic_only = _relevant_semantic_only(completeness, context_ids)
    cross_boundary_cycles = _relevant_cross_boundary_cycles(completeness, context_ids)

    warnings: list[str] = []
    if semantic_only:
        warnings.append(
            f"{len(semantic_only)} impacted semantic relationship(s) rely on explicit semantic evidence rather than static import reachability."
        )
    if cross_boundary_cycles:
        warnings.append(f"{len(cross_boundary_cycles)} impacted static cycle(s) cross architectural boundaries.")
    if proof_plan is not None and proof_plan.get("full_suite_fallback"):
        warnings.append("selective-CI shadow policy would retain full-suite fallback for this change")

    return {
        "schema_version": DECISION_SCHEMA_VERSION,
        "decision": {
            "architecture_disposition": disposition,
            "merge_authorization": "not-determined",
            "full_ci_required": True,
            "blocking_reasons": sorted(set(blocking_reasons)),
            "review_reasons": sorted(set(review_reasons)),
            "warnings": sorted(set(warnings)),
        },
        "inputs": {
            "canonical_graph": {
                "artifact": "docs/architecture/dependency-graph.v1.json",
                "sha256": str(impact.get("graph_sha256") or ""),
            },
            "comparison": impact.get("comparison", {}),
            "impact_report": {
                "artifact": "artifacts/graph-impact-report.json",
                "schema_version": str(impact.get("schema_version")),
                "sha256": _fingerprint(impact),
            },
            "proof_manifest": {
                "artifact": "artifacts/graph-proof-manifest.json",
                "schema_version": str(proof.get("schema_version")),
                "sha256": _fingerprint(proof),
            },
            "completeness_report": {
                "artifact": "artifacts/graph-completeness-report.json",
                "schema_version": str(completeness.get("schema_version")),
                "sha256": _fingerprint(completeness),
            },
        },
        "impact": {
            "changed_files": changed_files,
            "changed_node_ids": _ids(changed_nodes),
            "changed_node_sources": _sources(changed_nodes),
            "unmapped_changed_files": unmapped_changed_files,
            "relevant_invariant_ids": _ids(relevant_invariants),
            "risk_domain_ids": _ids(risk_domains),
            "affected_semantic_node_ids": _ids(affected_semantic_nodes),
            "dependency_semantic_node_ids": _ids(dependency_semantic_nodes),
        },
        "proof": {
            "selected_bundle_ids": _ids(selected_bundles),
            "required_tests": required_tests,
            "required_gates": required_gates,
            "review_gates": review_gates,
            "manual_review": manual_review,
            "full_suite_fallback": bool(proof_plan and proof_plan.get("full_suite_fallback")),
            "fallback_reasons": list(proof_plan.get("fallback_reasons", [])) if proof_plan is not None else [],
        },
        "completeness": {
            "integrity_pass": integrity.get("pass") is True,
            "missing_semantic_edge_evidence": sorted(
                str(item) for item in integrity.get("missing_semantic_edge_evidence", [])
            ),
            "missing_invariant_sources": sorted(str(item) for item in integrity.get("missing_invariant_sources", [])),
            "unacknowledged_blocking_findings": sorted(
                str(item) for item in integrity.get("unacknowledged_blocking_findings", [])
            ),
            "acknowledged_semantic_findings": sorted(
                str(item) for item in integrity.get("acknowledged_semantic_findings", [])
            ),
            "semantic_finding_count": int(integrity.get("semantic_finding_count", 0) or 0),
            "impacted_semantic_only_relationships": semantic_only,
            "impacted_cross_boundary_cycles": cross_boundary_cycles,
            "semantic_reconciliation_counts": completeness.get("semantic_reconciliation_counts", {}),
        },
        "metrics": {
            "changed_file_count": len(changed_files),
            "changed_node_count": len(changed_nodes),
            "unmapped_changed_file_count": len(unmapped_changed_files),
            "relevant_invariant_count": len(relevant_invariants),
            "risk_domain_count": len(risk_domains),
            "required_test_count": len(required_tests),
            "required_gate_count": len(required_gates),
            "review_gate_count": len(review_gates),
            "manual_review_count": len(manual_review),
            "impacted_semantic_only_count": len(semantic_only),
            "impacted_cross_boundary_cycle_count": len(cross_boundary_cycles),
        },
    }


def _print_human(manifest: dict[str, Any]) -> None:
    decision = manifest["decision"]
    metrics = manifest["metrics"]
    print(f"Architecture disposition: {decision['architecture_disposition']}")
    print("Merge authorization: not-determined (full CI remains authoritative)")
    print(
        "Impact: "
        f"{metrics['changed_file_count']} changed file(s), "
        f"{metrics['changed_node_count']} changed graph node(s), "
        f"{metrics['relevant_invariant_count']} relevant invariant(s)"
    )
    for reason in decision["blocking_reasons"]:
        print(f"BLOCK: {reason}")
    for reason in decision["review_reasons"]:
        print(f"REVIEW: {reason}")
    for warning in decision["warnings"]:
        print(f"WARN: {warning}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compose Ajenda graph artifacts into one architecture decision manifest."
    )
    parser.add_argument("--impact-report", required=True)
    parser.add_argument("--proof-manifest", required=True)
    parser.add_argument("--completeness-report", required=True)
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    try:
        impact = _load_json_object(Path(args.impact_report), label="impact report")
        proof = _load_json_object(Path(args.proof_manifest), label="proof manifest")
        completeness = _load_json_object(Path(args.completeness_report), label="completeness report")
        manifest = build_decision_manifest(impact, proof, completeness)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 1

    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    if args.as_json:
        print(rendered, end="")
    else:
        _print_human(manifest)
    return 1 if manifest["decision"]["architecture_disposition"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
