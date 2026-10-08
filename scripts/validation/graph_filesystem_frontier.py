#!/usr/bin/env python3
"""Build a machine-native federated filesystem Shadow for Frontier GRAFT+."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_DIR = Path(__file__).resolve().parent
for candidate in (REPO_ROOT, VALIDATION_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from build_dependency_graph import build_graph  # noqa: E402
from frontier_preflight import run_frontier_preflight  # noqa: E402
from graft_drift_controls import GRAPH_COMPONENTS  # noqa: E402
from graft_plus_frontier import validate_frontier_spec  # noqa: E402
from graft_plus_graft1st_reconciliation_check import IMPLEMENTATION_PROOFS, validate_conformance  # noqa: E402
from graph_completeness_audit import architectural_boundary, audit_graph  # noqa: E402
from graph_filesystem_projection import build_projection  # noqa: E402
from graph_runtime_contract_consumption import adjudicate_runtime_contracts_with_consumption  # noqa: E402

from backend.services.graft_artifact_lifecycle import GRAFT_ARTIFACT_LIFECYCLE_CONTRACTS  # noqa: E402

SERVICE_ROOT = "backend/services/"

# Frontier hypotheses, not implementation truth.
BOUNDED_CONTEXT: dict[str, str] = {
    "mission_acceptance.py": "mission_runtime",
    "mission_intake_quality.py": "mission_runtime",
    "mission_runtime_queue_admission_service.py": "mission_runtime",
    "mission_runtime_task_materialization_service.py": "mission_runtime",
    "mission_runtime_projection.py": "mission_runtime",
    "worker_claim_admission_service.py": "mission_runtime",
    "worker_run_admission_service.py": "mission_runtime",
    "worker_start_admission_service.py": "mission_runtime",
    "worker_runtime_service.py": "mission_runtime",
    "mission_executor.py": "mission_runtime",
    "execution_coordinator.py": "mission_runtime",
    "runtime_governor.py": "runtime_control",
    "runtime_maintainer.py": "runtime_control",
    "policy_guardian.py": "runtime_control",
    "control_specialist.py": "runtime_control",
    "operations_service.py": "runtime_control",
    "tenant_lifecycle.py": "tenant_lifecycle",
    "tenant_onboarding_orchestrator.py": "tenant_lifecycle",
    "onboarding_service.py": "tenant_lifecycle",
    "signup_abuse_guard.py": "tenant_lifecycle",
    "verification_token.py": "tenant_lifecycle",
    "verification_delivery.py": "tenant_lifecycle",
    "account_service.py": "commercial",
    "billing_stripe_integration.py": "commercial",
    "quota_enforcement.py": "commercial",
    "feature_flag_service.py": "commercial",
    "decision_episode_materialization.py": "decision_learning",
    "durable_experience_consolidation.py": "decision_learning",
    "document_artifacts.py": "artifacts",
    "draft_generation.py": "artifacts",
    "clerical_library.py": "artifacts",
    "webhook_dispatch.py": "webhooks",
    "webhook_secret_protector.py": "webhooks",
    "workforce_coordinator.py": "workforce",
    "workforce_provisioner.py": "workforce",
    "fleet_manager.py": "workforce",
    "mission_runtime_evidence_projection.py": "assurance",
    "continuous_assurance.py": "assurance",
    "runtime_admission_coverage.py": "assurance",
}

AUTHORITY_AWARE = dict(BOUNDED_CONTEXT)
for shared_name in (
    "execution_coordinator.py",
    "worker_runtime_service.py",
    "network_egress.py",
    "operating_charter.py",
    "mission_graph_integrity.py",
    "http_idempotency_authority.py",
):
    AUTHORITY_AWARE[shared_name] = "shared_authority"

CANDIDATES: dict[str, dict[str, str]] = {
    "current_layout_baseline": {},
    "bounded_context_projection": BOUNDED_CONTEXT,
    "authority_aware_hybrid_projection": AUTHORITY_AWARE,
}


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source(node: dict[str, Any]) -> str:
    return str(node.get("source") or "").replace("\\", "/")


def _flat_service_name(source: str) -> str | None:
    if not source.startswith(SERVICE_ROOT):
        return None
    rel = source[len(SERVICE_ROOT) :]
    if "/" in rel or rel == "__init__.py" or not rel.endswith(".py"):
        return None
    return rel


def _existing_service_package(source: str) -> str | None:
    if not source.startswith(SERVICE_ROOT):
        return None
    rel = source[len(SERVICE_ROOT) :]
    parts = [part for part in rel.split("/") if part]
    return parts[0] if len(parts) >= 2 else None


def _projected_boundary(node: dict[str, Any], assignments: dict[str, str]) -> str:
    source = _source(node)
    existing = _existing_service_package(source)
    if existing:
        return f"backend:services:{existing}"
    flat = _flat_service_name(source)
    if flat and flat in assignments:
        return f"backend:services:{assignments[flat]}"
    return architectural_boundary(node)


def _production(graph: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    nodes = {str(node["id"]): node for node in graph.get("nodes", []) if str(node.get("type")) != "test_module"}
    edges = [
        edge
        for edge in graph.get("edges", [])
        if str(edge.get("type")) != "tests"
        and str(edge.get("from")) in nodes
        and str(edge.get("to")) in nodes
    ]
    return nodes, edges


def _federated_evidence(runtime_report: dict[str, Any]) -> dict[str, set[str]]:
    tags: dict[str, set[str]] = defaultdict(set)

    for item in runtime_report.get("results", []):
        for source in item.get("witness_sources", []):
            if isinstance(source, str) and source:
                tags[source].add("runtime_contract_consumption")

    for node_key, proofs in IMPLEMENTATION_PROOFS.items():
        for proof in proofs:
            tags[proof.path].add(f"graft1st_implementation:{node_key}")

    for contract in GRAFT_ARTIFACT_LIFECYCLE_CONTRACTS:
        tags[contract.producer].add(f"artifact_lifecycle_producer:{contract.artifact_type}")

    for path in GRAPH_COMPONENTS:
        try:
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        except ValueError:
            continue
        tags[rel].add("drift_protected_graft_surface")

    return tags


def _candidate_state(
    *,
    graph: dict[str, Any],
    assignments: dict[str, str],
    audit: dict[str, Any],
) -> dict[str, Any]:
    nodes, edges = _production(graph)
    boundary_by_node = {node_id: _projected_boundary(node, assignments) for node_id, node in nodes.items()}
    cross_edges = sum(
        1 for edge in edges if boundary_by_node[str(edge["from"])] != boundary_by_node[str(edge["to"])]
    )

    projected_cycle_classes: Counter[str] = Counter()
    for cycle in audit.get("static_cycles", []):
        cycle_boundaries = {
            boundary_by_node[node_id] for node_id in cycle.get("nodes", []) if node_id in boundary_by_node
        }
        projected_cycle_classes["cross" if len(cycle_boundaries) > 1 else "intra"] += 1

    moved_sources = {
        f"{SERVICE_ROOT}{name}": boundary for name, boundary in assignments.items()
    }
    internalized_edges = 0
    externalized_edges = 0
    for edge in edges:
        source_id, target_id = str(edge["from"]), str(edge["to"])
        source_node, target_node = nodes[source_id], nodes[target_id]
        before_cross = architectural_boundary(source_node) != architectural_boundary(target_node)
        after_cross = boundary_by_node[source_id] != boundary_by_node[target_id]
        if before_cross and not after_cross:
            internalized_edges += 1
        elif not before_cross and after_cross:
            externalized_edges += 1

    unresolved = sorted(
        source
        for source in (_source(node) for node in nodes.values())
        if _flat_service_name(source) and source not in moved_sources
    )

    return {
        "x": cross_edges,
        "i": internalized_edges,
        "e": externalized_edges,
        "c": [projected_cycle_classes["cross"], projected_cycle_classes["intra"]],
        "u": unresolved,
    }


def build_shadow(frontier_spec: dict[str, Any]) -> dict[str, Any]:
    errors = validate_frontier_spec(frontier_spec)
    if errors:
        raise ValueError("invalid Frontier spec: " + "; ".join(errors))
    candidate_paths = frontier_spec.get("candidate_paths")
    if candidate_paths != list(CANDIDATES):
        raise ValueError("Frontier candidate_paths must exactly match filesystem Shadow candidates")

    graph = build_graph()
    audit = audit_graph(graph)
    filesystem = build_projection()
    runtime = adjudicate_runtime_contracts_with_consumption(graph)
    graft1st = validate_conformance()
    evidence = _federated_evidence(runtime)
    nodes, _ = _production(graph)

    source_paths = sorted({_source(node) for node in nodes.values() if _source(node)})
    file_id = {source: index for index, source in enumerate(source_paths)}

    candidate_states: list[dict[str, Any]] = []
    all_boundaries: set[str] = set()
    raw_states: dict[str, dict[str, Any]] = {}
    for candidate_name, assignments in CANDIDATES.items():
        state = _candidate_state(graph=graph, assignments=assignments, audit=audit)
        raw_states[candidate_name] = state
        for _source_name, boundary in assignments.items():
            all_boundaries.add(f"backend:services:{boundary}")
        all_boundaries.update(
            _projected_boundary(node, assignments)
            for node in nodes.values()
        )

    boundary_list = sorted(all_boundaries)
    boundary_id = {name: index for index, name in enumerate(boundary_list)}

    evidence_tags = sorted({tag for tags in evidence.values() for tag in tags})
    evidence_id = {tag: index for index, tag in enumerate(evidence_tags)}
    evidence_rows = sorted(
        [file_id[source], evidence_id[tag]]
        for source, tags in evidence.items()
        if source in file_id
        for tag in tags
    )

    for candidate_index, (candidate_name, assignments) in enumerate(CANDIDATES.items()):
        state = raw_states[candidate_name]
        assignment_rows = sorted(
            [file_id[f"{SERVICE_ROOT}{name}"], boundary_id[f"backend:services:{boundary}"]]
            for name, boundary in assignments.items()
            if f"{SERVICE_ROOT}{name}" in file_id
        )
        candidate_states.append(
            {
                "id": candidate_index,
                "a": assignment_rows,
                "m": [
                    state["x"],
                    state["i"],
                    state["e"],
                    state["c"][0],
                    state["c"][1],
                ],
                "u": [file_id[source] for source in state["u"] if source in file_id],
            }
        )

    projection_by_source = {
        item["source"]: item
        for item in filesystem.get("candidate_files", [])
        if isinstance(item.get("source"), str)
    }
    affinity_rows: list[list[int]] = []
    package_names = sorted(
        {
            str(affinity["package"])
            for item in projection_by_source.values()
            for affinity in item.get("package_affinity", [])
            if affinity.get("package")
        }
    )
    package_id = {name: index for index, name in enumerate(package_names)}
    for source, item in projection_by_source.items():
        if source not in file_id:
            continue
        for affinity in item.get("package_affinity", [])[:5]:
            package = str(affinity.get("package") or "")
            if package in package_id:
                affinity_rows.append(
                    [
                        file_id[source],
                        package_id[package],
                        int(affinity.get("score") or 0),
                        int(affinity.get("edge_count") or 0),
                    ]
                )

    return {
        "v": 1,
        "k": "graft_frontier_filesystem_shadow",
        "g": _canonical_sha256(graph),
        "f": source_paths,
        "b": boundary_list,
        "p": package_names,
        "t": evidence_tags,
        "q": [
            "x:cross_boundary_edges",
            "i:internalized_edges",
            "e:externalized_edges",
            "c0:cross_boundary_cycles",
            "c1:intra_boundary_cycles",
        ],
        "ev": evidence_rows,
        "af": sorted(affinity_rows),
        "c": candidate_states,
        "cn": list(CANDIDATES),
        "fg": {
            "runtime_contract_candidates": int(runtime.get("metrics", {}).get("candidate_count", 0)),
            "runtime_contract_satisfied": int(runtime.get("metrics", {}).get("satisfied_count", 0)),
            "graft1st_status": graft1st.get("status"),
            "graft1st_nodes": int(graft1st.get("node_count", 0)),
            "lifecycle_contracts": len(GRAFT_ARTIFACT_LIFECYCLE_CONTRACTS),
            "drift_protected_surfaces": len(GRAPH_COMPONENTS),
        },
        "auth": {
            "runtime": False,
            "source_mutation": False,
            "promotion": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontier-spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    preflight = run_frontier_preflight()
    if not preflight["ok"]:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({"v": 1, "k": "graft_frontier_filesystem_shadow", "ok": False, "pf": preflight},
                       sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        print("Frontier filesystem Shadow: preflight failed")
        return 1

    spec = json.loads(args.frontier_spec.read_text(encoding="utf-8"))
    artifact = build_shadow(spec)
    artifact["pf"] = preflight
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        "Frontier filesystem Shadow: "
        f"{len(artifact['f'])} files, {len(artifact['c'])} candidates, "
        f"{len(artifact['ev'])} federated evidence links"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
