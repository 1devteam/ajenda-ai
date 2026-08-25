#!/usr/bin/env python3
"""Select required proof from a graph-aware change impact report."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from build_dependency_graph import build_graph
from graph_impact_analysis import analyze_impact
from pr_invariant_classifier import _discover_changes


@dataclass(frozen=True, slots=True)
class ProofBundle:
    id: str
    title: str
    invariants: tuple[str, ...] = ()
    risk_domains: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    required_gates: tuple[str, ...] = ()
    review_gates: tuple[str, ...] = ()


SEMANTIC_HARDENING_TEST = "tests/unit/validation/test_graph_semantic_hardening.py"

PROOF_BUNDLES: tuple[ProofBundle, ...] = (
    ProofBundle(
        id="tenant-isolation-proof",
        title="Tenant isolation contract proof",
        invariants=("tenant-isolation",),
        risk_domains=("tenant-isolation",),
        tests=("tests/contract/api/test_tenant_isolation_policy.py", SEMANTIC_HARDENING_TEST),
        required_gates=("unit-tests",),
    ),
    ProofBundle(
        id="queue-authority-proof",
        title="Canonical queue-admission authority proof",
        invariants=("canonical-queue-admission",),
        tests=(
            "tests/unit/architecture/test_authority_ledger_contract.py",
            "tests/contract/api/test_mission_queue_contract.py",
        ),
        required_gates=("unit-tests",),
    ),
    ProofBundle(
        id="worker-spine-proof",
        title="Worker execution spine proof",
        invariants=("single-worker-spine",),
        risk_domains=("runtime-authority",),
        tests=(
            "tests/unit/services/test_worker_runtime_service_transaction_contract.py",
            "tests/integration/runtime/test_worker_executes_echo_task_real.py",
        ),
        required_gates=("unit-tests", "integration-tests"),
        review_gates=("live-runtime-proof",),
    ),
    ProofBundle(
        id="side-effect-approval-proof",
        title="Side-effect approval proof",
        invariants=("side-effect-approval",),
        tests=(
            "tests/unit/services/test_execution_coordinator.py",
            "tests/contract/api/test_task_queue_contract.py",
        ),
        required_gates=("unit-tests",),
    ),
    ProofBundle(
        id="retry-readmission-proof",
        title="Retry governance re-admission proof",
        invariants=("retry-readmission",),
        tests=("tests/unit/services/test_execution_coordinator.py",),
        required_gates=("unit-tests", "integration-tests"),
    ),
    ProofBundle(
        id="runtime-secret-proof",
        title="Runtime credential secret-boundary proof",
        invariants=("runtime-secret-boundary",),
        risk_domains=("credential-boundary",),
        tests=(
            "tests/unit/services/test_credential_runtime_authority.py",
            "tests/unit/tools/test_tool_runtime_authority.py",
        ),
        required_gates=("unit-tests",),
        review_gates=("live-runtime-proof",),
    ),
    ProofBundle(
        id="governed-egress-proof",
        title="Governed external egress proof",
        invariants=("governed-egress",),
        risk_domains=("external-egress",),
        tests=(
            "tests/unit/tools/test_tool_runtime_authority.py",
            "tests/unit/tools/test_provider_read_actions.py",
            SEMANTIC_HARDENING_TEST,
        ),
        required_gates=("unit-tests",),
        review_gates=("live-runtime-proof",),
    ),
    ProofBundle(
        id="state-ownership-proof",
        title="Atomic state ownership and consumption proof",
        invariants=(
            "lease-owner-integrity",
            "durable-idempotency-ownership",
            "single-use-secret-consumption",
            "atomic-quota-reservation",
        ),
        tests=(SEMANTIC_HARDENING_TEST,),
        required_gates=("unit-tests",),
    ),
    ProofBundle(
        id="connector-oauth-proof",
        title="Connector OAuth separation proof",
        invariants=("connector-oauth-separation",),
        risk_domains=("credential-boundary",),
        tests=("tests/contract/api/test_provider_credentials_routes.py",),
        required_gates=("unit-tests",),
        review_gates=("live-runtime-proof",),
    ),
    ProofBundle(
        id="authority-class-proof",
        title="Authority-class stability proof",
        invariants=("capability-not-authority", "authority-class-stability"),
        tests=("tests/unit/architecture/test_authority_ledger_contract.py",),
        required_gates=("unit-tests",),
    ),
    ProofBundle(
        id="persistence-proof",
        title="Persistence and migration proof",
        risk_domains=("persistence",),
        required_gates=("unit-tests", "migration-round-trip"),
    ),
    ProofBundle(
        id="frontend-contract-proof",
        title="Frontend/backend contract proof",
        risk_domains=("frontend-contract",),
        required_gates=("frontend-build-audit",),
    ),
    ProofBundle(
        id="configuration-proof",
        title="Configuration contract proof",
        risk_domains=("configuration",),
        required_gates=("lint-type-check",),
    ),
    ProofBundle(
        id="action-contract-proof",
        title="Action and capability contract proof",
        risk_domains=("action-contract",),
        required_gates=("unit-tests",),
    ),
)


def _ids(items: list[dict[str, Any]]) -> set[str]:
    return {str(item["id"]) for item in items if item.get("id")}


def select_proofs(report: dict[str, Any]) -> dict[str, Any]:
    invariant_items = report.get("relevant_invariants", [])
    invariant_ids = _ids(invariant_items)
    risk_ids = _ids(report.get("risk_domains", []))

    selected: list[ProofBundle] = []
    for bundle in PROOF_BUNDLES:
        invariant_match = bool(invariant_ids.intersection(bundle.invariants))
        risk_match = bool(risk_ids.intersection(bundle.risk_domains))
        if invariant_match or risk_match:
            selected.append(bundle)

    impacted_tests = sorted(
        {
            str(item["source"])
            for item in report.get("impacted_tests", [])
            if isinstance(item.get("source"), str) and item["source"]
        }
    )
    required_tests = sorted({test for bundle in selected for test in bundle.tests}.union(impacted_tests))
    required_gates = sorted({gate for bundle in selected for gate in bundle.required_gates})
    review_gates = sorted({gate for bundle in selected for gate in bundle.review_gates})

    changed_nodes = report.get("changed_nodes", [])
    if any(
        node.get("type")
        in {"python_module", "service_module", "migration", "database_table", "network_egress_sink", "state_resource"}
        for node in changed_nodes
    ):
        required_gates = sorted(set(required_gates).union({"unit-tests"}))

    manual_review: list[str] = []
    if report.get("unmapped_changed_files"):
        manual_review.append("Review unmapped changed files; the canonical graph does not yet model them.")
    for invariant in invariant_items:
        invariant_id = str(invariant.get("id") or "")
        status = str(invariant.get("status") or "")
        if status == "policy_drift":
            manual_review.append(
                f"Invariant {invariant_id} is recorded as policy drift and requires human architecture review."
            )
        elif status == "known_violation":
            manual_review.append(
                f"Invariant {invariant_id} has a known baseline violation; verify the change does not expand it and remove the acknowledgement only with repair proof."
            )

    return {
        "schema_version": "1.1",
        "selected_bundles": [
            {
                "id": bundle.id,
                "title": bundle.title,
                "matched_invariants": sorted(invariant_ids.intersection(bundle.invariants)),
                "matched_risk_domains": sorted(risk_ids.intersection(bundle.risk_domains)),
            }
            for bundle in selected
        ],
        "required_tests": required_tests,
        "required_gates": required_gates,
        "review_gates": review_gates,
        "manual_review": manual_review,
        "metrics": {
            "selected_bundle_count": len(selected),
            "required_test_count": len(required_tests),
            "required_gate_count": len(required_gates),
            "review_gate_count": len(review_gates),
            "manual_review_count": len(manual_review),
        },
    }


def _print_human(manifest: dict[str, Any]) -> None:
    metrics = manifest["metrics"]
    print(
        "Proof selection: "
        f"{metrics['selected_bundle_count']} bundle(s), "
        f"{metrics['required_test_count']} test(s), "
        f"{metrics['required_gate_count']} required gate(s)"
    )
    for test in manifest["required_tests"]:
        print(f"TEST: {test}")
    for gate in manifest["required_gates"]:
        print(f"GATE: {gate}")
    for gate in manifest["review_gates"]:
        print(f"REVIEW GATE: {gate}")
    for item in manifest["manual_review"]:
        print(f"MANUAL REVIEW: {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Select graph-aware proof obligations for a change.")
    parser.add_argument("--impact-report")
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--output")
    args = parser.parse_args()

    if bool(args.base_ref) != bool(args.head_ref):
        parser.error("--base-ref and --head-ref must be supplied together")

    if args.impact_report:
        report = json.loads(Path(args.impact_report).read_text(encoding="utf-8"))
    else:
        if args.changed_file:
            changed = sorted(set(args.changed_file))
        else:
            try:
                changed, _ = _discover_changes(args.base_ref, args.head_ref)
            except RuntimeError as exc:
                print(f"FAIL: unable to determine changed files: {exc}")
                return 1
        report = analyze_impact(build_graph(), changed)

    manifest = select_proofs(report)
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    if args.as_json:
        print(rendered, end="")
    else:
        _print_human(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
