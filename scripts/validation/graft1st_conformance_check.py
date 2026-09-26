"""Validate the frozen GRAFT1st package against implementation-backed ownership proof."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.services.vertical_ops.graft1st_contracts import (  # noqa: E402
    GRAFT1ST_CONTRACT_PACKAGE_ID,
    GRAFT1ST_CONTRACT_PACKAGE_VERSION,
    CanonicalContractPackage,
    InterminglingSimulationSuite,
    NodeImplementationStatus,
)

PACKAGE_PATH = REPO_ROOT / "tests/fixtures/graft1st/gtm_crm_communications_contract_package.v2.json"
SIMULATION_PATH = REPO_ROOT / "tests/fixtures/graft1st/intermingling_simulations.v1.json"


@dataclass(frozen=True, slots=True)
class SourceProof:
    path: str
    required_tokens: tuple[str, ...]


# These are ownership/conformance proofs, not alternate action registrations.
# Nodes marked ``new`` remain intentionally absent until their owning package lands.
IMPLEMENTATION_PROOFS: dict[str, tuple[SourceProof, ...]] = {
    "mission.interpret": (
        SourceProof("backend/services/mission_composition/service.py", ("MissionCompositionService",)),
    ),
    "vertical.select": (
        SourceProof("backend/services/mission_composition/vertical_know_how.py", ("REVOPS_V2_KNOW_HOW",)),
    ),
    "graph.compile": (
        SourceProof("backend/services/mission_composition/plan_compiler.py", ("compile_task_graph_preview",)),
    ),
    "task.materialize": (
        SourceProof(
            "backend/services/mission_runtime_task_materialization_service.py",
            ("MissionRuntimeTaskMaterializationService", "def materialize"),
        ),
    ),
    "research.discover": (SourceProof("backend/services/tools/standalone_actions.py", ('name="web.research"',)),),
    "sales.qualify": (SourceProof("backend/services/tools/sales_actions.py", ('name="sales.qualify"',)),),
    "research.synthesize_report": (
        SourceProof("backend/services/tools/standalone_actions.py", ('name="research.synthesize_report"',)),
    ),
    "crm.observe": (SourceProof("backend/services/tools/crm_actions.py", ('name="crm.observe"',)),),
    "crm.reconcile": (
        SourceProof("backend/services/vertical_ops/crm_reconciliation.py", ("plan_crm_reconciliation",)),
        SourceProof("backend/services/tools/crm_actions.py", ('name="crm.reconcile"',)),
    ),
    "crm.mutate": (SourceProof("backend/services/tools/crm_actions.py", ('name="crm.mutate"',)),),
    "crm.verify_effect": (SourceProof("backend/services/tools/crm_actions.py", ('name="crm.verify_effect"',)),),
    "engagement.draft": (SourceProof("backend/services/tools/sales_actions.py", ('name="sales.draft_followup"',)),),
    "communication.authorize": (
        SourceProof("backend/services/tools/schemas.py", ("class SideEffectAuthorizationV2", "invocation_sha256")),
        SourceProof(
            "backend/services/execution_coordinator.py",
            ("approve_review_and_queue", 'constraints["side_effect_authorization"]'),
        ),
    ),
    "mission.reconcile": (
        SourceProof("backend/services/worker_runtime_service.py", ("_maybe_rollup_mission_status",)),
        SourceProof("backend/services/mission_composition/revops_deliverable.py", ("result_semantics",)),
    ),
    "outcome.review": (SourceProof("backend/api/routes/outcome_review.py", ("OutcomeReviewRepository",)),),
    "knowledge.qualify": (
        SourceProof("backend/services/tools/knowledge_actions.py", ('name="knowledge.record_qualification"',)),
    ),
}


def validate_conformance(
    *,
    repo_root: Path = REPO_ROOT,
    package_path: Path = PACKAGE_PATH,
    simulation_path: Path = SIMULATION_PATH,
) -> dict[str, Any]:
    package = CanonicalContractPackage.model_validate_json(package_path.read_text(encoding="utf-8"))
    simulations = InterminglingSimulationSuite.model_validate_json(simulation_path.read_text(encoding="utf-8"))

    errors: list[str] = []
    if package.package_id != GRAFT1ST_CONTRACT_PACKAGE_ID:
        errors.append("package id differs from the code constant")
    if package.package_version != GRAFT1ST_CONTRACT_PACKAGE_VERSION:
        errors.append("package version differs from the code constant")
    if simulations.contract_package_version != package.package_version:
        errors.append("simulation suite targets a different package version")

    nodes_by_key = {node.node_key: node for node in package.nodes}
    active_worktree = sorted(
        node.node_key
        for node in package.nodes
        if node.implementation_status == NodeImplementationStatus.ACTIVE_WORKTREE
    )
    if active_worktree:
        errors.append(f"clean frozen package cannot retain active_worktree statuses: {active_worktree}")

    mapped_nodes = set(IMPLEMENTATION_PROOFS)
    unknown_mappings = sorted(mapped_nodes - set(nodes_by_key))
    if unknown_mappings:
        errors.append(f"implementation proof references unknown nodes: {unknown_mappings}")

    unproved_non_new = sorted(
        node.node_key
        for node in package.nodes
        if node.implementation_status != NodeImplementationStatus.NEW and node.node_key not in mapped_nodes
    )
    if unproved_non_new:
        errors.append(f"non-new nodes lack implementation proof: {unproved_non_new}")

    for node_key, proofs in IMPLEMENTATION_PROOFS.items():
        node = nodes_by_key.get(node_key)
        if node is None:
            continue
        if node.implementation_status == NodeImplementationStatus.NEW:
            errors.append(f"implemented node is still classified new: {node_key}")
        for proof in proofs:
            source_path = repo_root / proof.path
            if not source_path.is_file():
                errors.append(f"implementation proof source is missing for {node_key}: {proof.path}")
                continue
            source = source_path.read_text(encoding="utf-8")
            missing_tokens = [token for token in proof.required_tokens if token not in source]
            if missing_tokens:
                errors.append(f"implementation proof tokens missing for {node_key} in {proof.path}: {missing_tokens}")

    scenario_nodes = {step.node_key for scenario in simulations.scenarios for step in scenario.steps}
    unknown_scenario_nodes = sorted(scenario_nodes - set(nodes_by_key))
    if unknown_scenario_nodes:
        errors.append(f"simulation suite references unknown nodes: {unknown_scenario_nodes}")

    report = {
        "schema_version": 1,
        "package_id": package.package_id,
        "package_version": package.package_version,
        "node_count": len(package.nodes),
        "edge_count": len(package.edges),
        "scenario_count": len(simulations.scenarios),
        "implementation_proof_node_count": len(IMPLEMENTATION_PROOFS),
        "status_counts": {
            status.value: sum(1 for node in package.nodes if node.implementation_status == status)
            for status in NodeImplementationStatus
        },
        "errors": errors,
        "status": "passed" if not errors else "failed",
    }
    return report


def main() -> int:
    report = validate_conformance()
    if report["errors"]:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    print(
        "PASS: GRAFT1st conformance checks passed "
        f"({report['node_count']} nodes, {report['edge_count']} edges, "
        f"{report['scenario_count']} simulations, "
        f"{report['implementation_proof_node_count']} implementation proofs)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
