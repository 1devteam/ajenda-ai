from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts" / "validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

BUILD_PATH = VALIDATION_DIR / "build_dependency_graph.py"
BUILD_SPEC = importlib.util.spec_from_file_location("single_use_credential_graph_build", BUILD_PATH)
assert BUILD_SPEC is not None and BUILD_SPEC.loader is not None
BUILD = importlib.util.module_from_spec(BUILD_SPEC)
sys.modules[BUILD_SPEC.name] = BUILD
BUILD_SPEC.loader.exec_module(BUILD)

AUDIT_PATH = VALIDATION_DIR / "graph_completeness_audit.py"
AUDIT_SPEC = importlib.util.spec_from_file_location("single_use_credential_graph_audit", AUDIT_PATH)
assert AUDIT_SPEC is not None and AUDIT_SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(AUDIT_SPEC)
sys.modules[AUDIT_SPEC.name] = AUDIT
AUDIT_SPEC.loader.exec_module(AUDIT)


def _graph() -> dict:
    return BUILD.build_graph()


def test_single_use_credentials_are_modeled_as_transactionally_serialized() -> None:
    graph = _graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}
    invariants = {item["id"]: item for item in graph["invariants"]}
    finding_ids = {item["id"] for item in graph["semantic_findings"]}

    repaired_findings = {
        "state-ownership:verification-token",
        "state-ownership:bootstrap-api-key",
        "state-ownership:customer-refresh-token",
    }
    assert repaired_findings.isdisjoint(finding_ids)

    invariant = invariants["single-use-secret-consumption"]
    assert invariant["status"] == "enforced"
    assert invariant["applies_to"] == [
        "state:verification-token",
        "state:bootstrap-api-key",
        "state:customer-refresh-token",
    ]

    assert nodes["state:verification-token"]["source"] == "backend/repositories/tenant_member_repository.py"
    assert nodes["state:bootstrap-api-key"]["source"] == "backend/repositories/api_key_repository.py"
    assert nodes["state:customer-refresh-token"]["source"] == "backend/repositories/customer_auth_session_repository.py"

    assert (
        "py:backend.repositories.tenant_member_repository",
        "state:verification-token",
        "serializes_state",
    ) in edges
    assert (
        "py:backend.repositories.api_key_repository",
        "state:bootstrap-api-key",
        "serializes_state",
    ) in edges
    assert (
        "py:backend.repositories.customer_auth_session_repository",
        "state:customer-refresh-token",
        "serializes_state",
    ) in edges

    residual_findings = {
        "state-ownership:api-key-quota-capacity",
    }
    assert residual_findings.issubset(finding_ids)
    assert "state-ownership:smtp-send-claim" not in finding_ids


def test_single_use_credential_graph_closure_preserves_semantic_integrity() -> None:
    report = AUDIT.audit_graph(_graph())
    assert report["integrity"]["pass"] is True
    assert report["integrity"]["unacknowledged_blocking_findings"] == []
