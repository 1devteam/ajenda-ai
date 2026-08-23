from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts/validation"
for module_name in ("build_dependency_graph", "pr_invariant_classifier", "graph_impact_analysis"):
    module_path = VALIDATION_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

MODULE_PATH = VALIDATION_DIR / "graph_proof_selection.py"
SPEC = importlib.util.spec_from_file_location("graph_proof_selection", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _report() -> dict:
    return {
        "changed_nodes": [{"id": "py:backend.services.execution_coordinator", "type": "python_module"}],
        "unmapped_changed_files": [],
        "impacted_tests": [
            {
                "id": "test:tests/unit/services/test_execution_coordinator.py",
                "source": "tests/unit/services/test_execution_coordinator.py",
                "covers_affected_nodes": ["py:backend.services.execution_coordinator"],
            }
        ],
        "relevant_invariants": [
            {"id": "side-effect-approval", "status": "enforced"},
            {"id": "retry-readmission", "status": "enforced"},
        ],
        "risk_domains": [{"id": "runtime-authority", "title": "Runtime authority"}],
    }


def test_invariants_and_risk_domains_select_required_proof_bundles() -> None:
    manifest = MODULE.select_proofs(_report())

    bundle_ids = {bundle["id"] for bundle in manifest["selected_bundles"]}
    assert "worker-spine-proof" in bundle_ids
    assert "side-effect-approval-proof" in bundle_ids
    assert "retry-readmission-proof" in bundle_ids
    assert "unit-tests" in manifest["required_gates"]
    assert "integration-tests" in manifest["required_gates"]


def test_graph_discovered_impacted_tests_are_preserved() -> None:
    report = _report()
    report["impacted_tests"].append(
        {
            "id": "test:tests/integration/runtime/test_custom_runtime_path.py",
            "source": "tests/integration/runtime/test_custom_runtime_path.py",
            "covers_affected_nodes": ["py:backend.services.execution_coordinator"],
        }
    )

    manifest = MODULE.select_proofs(report)

    assert "tests/integration/runtime/test_custom_runtime_path.py" in manifest["required_tests"]


def test_unmapped_files_require_manual_review() -> None:
    report = _report()
    report["unmapped_changed_files"] = ["deploy/new-runtime-wrapper.sh"]

    manifest = MODULE.select_proofs(report)

    assert any("unmapped" in item.lower() for item in manifest["manual_review"])


def test_policy_drift_invariant_requires_manual_architecture_review() -> None:
    report = _report()
    report["relevant_invariants"] = [{"id": "route-service-injection", "status": "policy_drift"}]
    report["risk_domains"] = []

    manifest = MODULE.select_proofs(report)

    assert any("route-service-injection" in item for item in manifest["manual_review"])


def test_nonproduction_tooling_change_does_not_invent_required_proofs() -> None:
    report = {
        "changed_nodes": [{"id": "test:x", "type": "test_module"}],
        "unmapped_changed_files": ["scripts/validation/new_tool.py"],
        "impacted_tests": [],
        "relevant_invariants": [],
        "risk_domains": [],
    }

    manifest = MODULE.select_proofs(report)

    assert manifest["selected_bundles"] == []
    assert manifest["required_tests"] == []
    assert manifest["required_gates"] == []
    assert manifest["manual_review"]
