from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts" / "validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

MODULE_PATH = VALIDATION_DIR / "graph_architecture_decision.py"
SPEC = importlib.util.spec_from_file_location("graph_architecture_decision", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

build_decision_manifest = MODULE.build_decision_manifest
_fingerprint = MODULE._fingerprint


def _impact() -> dict:
    return {
        "schema_version": "1.0",
        "changed_files": ["backend/services/example.py"],
        "changed_nodes": [
            {
                "id": "py:backend.services.example",
                "type": "python_module",
                "source": "backend/services/example.py",
            }
        ],
        "unmapped_changed_files": [],
        "upstream_consumers": [],
        "downstream_dependencies": [],
        "affected_semantic_nodes": [],
        "dependency_semantic_nodes": [],
        "relevant_invariants": [],
        "risk_domains": [],
    }


def _proof() -> dict:
    return {
        "schema_version": "1.0",
        "selected_bundles": [],
        "required_tests": [],
        "required_gates": ["unit-tests"],
        "review_gates": [],
        "manual_review": [],
    }


def _completeness() -> dict:
    return {
        "schema_version": "1.0",
        "integrity": {
            "pass": True,
            "missing_semantic_edge_evidence": [],
            "missing_invariant_sources": [],
        },
        "semantic_reconciliation": [],
        "semantic_reconciliation_counts": {},
        "static_cycles": [],
    }


def test_clear_means_architecture_clear_not_merge_authorized():
    manifest = build_decision_manifest(_impact(), _proof(), _completeness())

    assert manifest["decision"]["architecture_disposition"] == "clear"
    assert manifest["decision"]["merge_authorization"] == "not-determined"
    assert manifest["decision"]["full_ci_required"] is True
    assert manifest["decision"]["blocking_reasons"] == []
    assert manifest["decision"]["review_reasons"] == []


def test_accepts_function_layer_impact_schema_1_2():
    impact = _impact()
    impact["schema_version"] = "1.2"
    impact["changed_nodes"] = [
        {
            "id": "fn:backend.services.mission_composition.intent_interpreter:_classify_clause",
            "type": "python_function",
            "source": "backend/services/mission_composition/intent_interpreter.py",
            "decision_role": "classifies_materiality",
        }
    ]

    manifest = build_decision_manifest(impact, _proof(), _completeness())

    assert manifest["decision"]["architecture_disposition"] == "clear"
    assert manifest["inputs"]["impact_report"]["schema_version"] == "1.2"
    assert manifest["impact"]["changed_node_ids"] == [
        "fn:backend.services.mission_composition.intent_interpreter:_classify_clause"
    ]


def test_manual_review_and_runtime_proof_require_review():
    proof = _proof()
    proof["manual_review"] = ["Review policy drift."]
    proof["review_gates"] = ["live-runtime-proof"]

    manifest = build_decision_manifest(_impact(), proof, _completeness())

    assert manifest["decision"]["architecture_disposition"] == "review-required"
    assert "Review policy drift." in manifest["decision"]["review_reasons"]
    assert "review-only gate required: live-runtime-proof" in manifest["decision"]["review_reasons"]


def test_failed_completeness_integrity_blocks():
    completeness = _completeness()
    completeness["integrity"] = {
        "pass": False,
        "missing_semantic_edge_evidence": ["backend/missing.py"],
        "missing_invariant_sources": [],
    }

    manifest = build_decision_manifest(_impact(), _proof(), completeness)

    assert manifest["decision"]["architecture_disposition"] == "blocked"
    assert "canonical graph completeness integrity failed" in manifest["decision"]["blocking_reasons"]
    assert manifest["completeness"]["missing_semantic_edge_evidence"] == ["backend/missing.py"]


def test_invalid_proof_gate_blocks_fail_closed():
    proof = _proof()
    proof["required_gates"] = ["unknown-gate"]

    manifest = build_decision_manifest(_impact(), proof, _completeness())

    assert manifest["decision"]["architecture_disposition"] == "blocked"
    assert any(
        reason.startswith("proof manifest validation failed: unknown required gate")
        for reason in manifest["decision"]["blocking_reasons"]
    )


def test_impacted_semantic_only_and_cross_boundary_cycles_are_warnings_not_violations():
    impact = _impact()
    impact["upstream_consumers"] = [
        {
            "id": "py:backend.services.consumer",
            "type": "python_module",
            "source": "backend/services/consumer.py",
        }
    ]
    completeness = _completeness()
    completeness["semantic_reconciliation"] = [
        {
            "from": "py:backend.services.consumer",
            "to": "py:backend.services.example",
            "type": "calls",
            "evidence": "backend/services/consumer.py",
            "classification": "semantic-only",
        }
    ]
    completeness["static_cycles"] = [
        {
            "nodes": ["py:backend.services.consumer", "py:backend.api.routes.example"],
            "boundaries": ["backend:services", "backend:api"],
            "classification": "cross-boundary",
        }
    ]

    manifest = build_decision_manifest(impact, _proof(), completeness)

    assert manifest["decision"]["architecture_disposition"] == "clear"
    assert manifest["metrics"]["impacted_semantic_only_count"] == 1
    assert manifest["metrics"]["impacted_cross_boundary_cycle_count"] == 1
    assert len(manifest["decision"]["warnings"]) == 2


def test_input_fingerprints_are_deterministic_for_key_order():
    left = {"schema_version": "1.0", "a": 1, "b": {"x": 2, "y": 3}}
    right = {"b": {"y": 3, "x": 2}, "a": 1, "schema_version": "1.0"}

    assert _fingerprint(left) == _fingerprint(right)
