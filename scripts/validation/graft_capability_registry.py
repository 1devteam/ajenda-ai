#!/usr/bin/env python3
"""Machine registry for Ajenda GRAFT reasoning surfaces."""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Concepts are preserved; representation is compact and machine-addressable.
# Frontier remains external_observer and is not part of the routine core.
_SURFACES: tuple[tuple[str, str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "canonical_graph",
        "scripts/validation/build_dependency_graph.py",
        "diagnostic",
        (
            "source",
            "semantic_inventory",
            "deployment_inventory",
            "runtime_contract_inventory",
            "runtime_action_selection_inventory",
            "runtime_support_inventory",
            "function_inventory",
        ),
        ("graph",),
    ),
    (
        "semantic_inventory",
        "scripts/validation/graph_semantic_inventory.py",
        "diagnostic",
        ("source", "semantic_overlay"),
        ("db_rls_facts", "egress_facts", "semantic_findings"),
    ),
    (
        "deployment_inventory",
        "scripts/validation/graph_deployment_inventory.py",
        "diagnostic",
        ("source",),
        ("deployment_facts",),
    ),
    (
        "runtime_contract_inventory",
        "scripts/validation/graph_runtime_contract_inventory.py",
        "diagnostic",
        ("source",),
        ("business_jobs", "runtime_artifacts", "runtime_bindings"),
    ),
    (
        "runtime_action_selection_inventory",
        "scripts/validation/graph_runtime_action_selection_inventory.py",
        "diagnostic",
        ("source",),
        ("resolver_selection_facts",),
    ),
    (
        "runtime_support_inventory",
        "scripts/validation/graph_runtime_support_inventory.py",
        "diagnostic",
        ("source",),
        ("runtime_support_facts",),
    ),
    (
        "function_inventory",
        "scripts/validation/graph_function_inventory.py",
        "diagnostic",
        ("source",),
        ("selected_function_graph",),
    ),
    (
        "completeness",
        "scripts/validation/graph_completeness_audit.py",
        "diagnostic",
        ("graph",),
        ("centrality", "boundary_matrix", "cycles", "semantic_reconciliation", "integrity"),
    ),
    (
        "impact",
        "scripts/validation/graph_impact_analysis.py",
        "diagnostic",
        ("graph", "change_set"),
        ("blast_radius", "impacted_tests", "risk_domains", "relevant_invariants"),
    ),
    (
        "proof_selection",
        "scripts/validation/graph_proof_selection.py",
        "diagnostic",
        ("blast_radius", "relevant_invariants", "risk_domains"),
        ("proof_bundles", "required_tests", "required_gates", "review_gates"),
    ),
    (
        "architecture_decision",
        "scripts/validation/graph_architecture_decision.py",
        "diagnostic",
        ("blast_radius", "proof_bundles", "integrity"),
        ("architecture_disposition", "review_reasons"),
    ),
    (
        "runtime_contract_adjudication",
        "scripts/validation/graph_runtime_contract_adjudication.py",
        "diagnostic",
        ("graph", "runtime_bindings", "source"),
        ("binding_adjudication",),
    ),
    (
        "runtime_contract_consumption",
        "scripts/validation/graph_runtime_contract_consumption.py",
        "diagnostic",
        ("binding_adjudication", "source"),
        ("typed_consumption_witness",),
    ),
    (
        "runtime_action_selection_adjudication",
        "scripts/validation/graph_runtime_action_selection_adjudication.py",
        "diagnostic",
        ("binding_adjudication", "resolver_selection_facts", "source"),
        ("selection_witness",),
    ),
    (
        "runtime_instantiated_applicability",
        "scripts/validation/graph_runtime_instantiated_applicability.py",
        "diagnostic",
        ("binding_adjudication", "selection_witness", "runtime_instance"),
        ("instantiated_applicability",),
    ),
    (
        "runtime_impact",
        "scripts/validation/graph_runtime_impact.py",
        "diagnostic",
        ("blast_radius", "runtime_evidence"),
        ("static_runtime_join",),
    ),
    (
        "mission_instance_integrity",
        "scripts/validation/graph_mission_instance_integrity.py",
        "diagnostic",
        ("runtime_instance",),
        ("mission_instance_findings",),
    ),
    (
        "runtime_reconciliation",
        "scripts/validation/graft_runtime_reconciliation.py",
        "diagnostic",
        ("runtime_snapshot",),
        ("runtime_reconciliation",),
    ),
    (
        "artifact_lifecycle",
        "backend/services/graft_artifact_lifecycle.py",
        "governance_metadata",
        ("artifact_contracts",),
        ("artifact_lifecycle_facts",),
    ),
    (
        "drift_controls",
        "scripts/validation/graft_drift_controls.py",
        "governance_gate",
        ("source", "artifact_lifecycle_facts", "runtime_admission_coverage"),
        ("drift_findings", "graph_freshness"),
    ),
    (
        "runtime_admission_integrity",
        "backend/services/mission_graph_integrity.py",
        "read_only_admission",
        ("mission_instruction", "task_graph", "credential_metadata"),
        ("admission_integrity_findings",),
    ),
    (
        "runtime_evidence_projection",
        "backend/services/mission_runtime_evidence_projection.py",
        "read_only_observation",
        ("persisted_runtime_state",),
        ("runtime_evidence",),
    ),
    (
        "graft1st",
        "backend/services/vertical_ops/graft1st_contracts.py",
        "declarative",
        ("contract_package",),
        ("future_state_contracts", "intermingling_simulations"),
    ),
    (
        "graft1st_reconciliation",
        "scripts/validation/graft_plus_graft1st_reconciliation_check.py",
        "diagnostic",
        ("future_state_contracts", "source", "artifact_lifecycle_facts"),
        ("implementation_ownership_proof",),
    ),
    (
        "composition_shadow",
        "backend/services/mission_composition/shadow_preview.py",
        "read_only_observation",
        ("composition_expectation", "runtime_artifacts"),
        ("shadow_preview", "runtime_reconciliation"),
    ),
    (
        "graft_architecture",
        "backend/services/mission_composition/intelligence_envelope.py",
        "intelligence",
        (
            "graph",
            "semantic_identity",
            "runtime_evidence",
            "knowledge",
            "composition_expectation",
        ),
        ("architecture_interpretation", "intelligence_envelope"),
    ),
    (
        "target_filesystem_placement",
        "scripts/validation/graph_target_filesystem_placement.py",
        "diagnostic",
        (
            "graph",
            "centrality",
            "cycles",
            "blast_radius",
            "proof_bundles",
            "typed_consumption_witness",
            "selection_witness",
            "deployment_facts",
            "runtime_support_facts",
            "implementation_ownership_proof",
            "artifact_lifecycle_facts",
            "runtime_admission_coverage",
            "target_architecture",
        ),
        ("placement_manifest",),
    ),
    (
        "filesystem_projection",
        "scripts/validation/graph_filesystem_projection.py",
        "diagnostic",
        ("graph", "centrality", "cycles"),
        ("filesystem_affinity", "filesystem_risk"),
    ),
    (
        "frontier",
        "scripts/validation/graft_plus_frontier.py",
        "external_observer",
        ("graph", "frontier_spec", "experiment_evidence"),
        ("counterfactual_comparison",),
    ),
    (
        "filesystem_frontier",
        "scripts/validation/graph_filesystem_frontier.py",
        "external_observer",
        (
            "graph",
            "centrality",
            "cycles",
            "filesystem_affinity",
            "typed_consumption_witness",
            "implementation_ownership_proof",
            "artifact_lifecycle_facts",
            "drift_findings",
        ),
        ("filesystem_counterfactuals",),
    ),
)


def _sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_machine_registry() -> dict[str, Any]:
    providers = [row[0] for row in _SURFACES]
    sources = [row[1] for row in _SURFACES]
    authorities = sorted({row[2] for row in _SURFACES})
    concepts = sorted({concept for row in _SURFACES for concept in (*row[3], *row[4])})

    authority_id = {name: index for index, name in enumerate(authorities)}
    concept_id = {name: index for index, name in enumerate(concepts)}

    rows = [
        [
            index,
            authority_id[authority],
            [concept_id[item] for item in consumes],
            [concept_id[item] for item in produces],
        ]
        for index, (_provider, _source, authority, consumes, produces) in enumerate(_SURFACES)
    ]
    core = [index for index, row in enumerate(_SURFACES) if row[2] != "external_observer"]
    observers = [index for index, row in enumerate(_SURFACES) if row[2] == "external_observer"]

    artifact = {
        "v": 1,
        "k": "graft_capability_registry",
        "p": providers,
        "s": sources,
        "a": authorities,
        "c": concepts,
        "r": rows,
        "core": core,
        "obs": observers,
    }
    artifact["h"] = _sha(artifact)
    return artifact


if __name__ == "__main__":
    print(json.dumps(build_machine_registry(), sort_keys=True, separators=(",", ":")))
