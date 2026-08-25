from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts" / "validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

BUILD_PATH = VALIDATION_DIR / "build_dependency_graph.py"
BUILD_SPEC = importlib.util.spec_from_file_location("http_idempotency_graph_build", BUILD_PATH)
assert BUILD_SPEC is not None and BUILD_SPEC.loader is not None
BUILD = importlib.util.module_from_spec(BUILD_SPEC)
sys.modules[BUILD_SPEC.name] = BUILD
BUILD_SPEC.loader.exec_module(BUILD)

AUDIT_PATH = VALIDATION_DIR / "graph_completeness_audit.py"
AUDIT_SPEC = importlib.util.spec_from_file_location("http_idempotency_graph_audit", AUDIT_PATH)
assert AUDIT_SPEC is not None and AUDIT_SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(AUDIT_SPEC)
sys.modules[AUDIT_SPEC.name] = AUDIT
AUDIT_SPEC.loader.exec_module(AUDIT)


def _graph() -> dict:
    return BUILD.build_graph()


def test_http_idempotency_is_modeled_as_enforced_durable_authority() -> None:
    graph = _graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}
    invariants = {item["id"]: item for item in graph["invariants"]}
    finding_ids = {item["id"] for item in graph["semantic_findings"]}

    assert "state-ownership:http-idempotency-key" not in finding_ids

    http_invariant = invariants["http-idempotency-ownership"]
    assert http_invariant["status"] == "enforced"
    assert http_invariant["applies_to"] == ["state:http-idempotency-key"]

    residual_invariant = invariants["durable-idempotency-ownership"]
    assert residual_invariant["status"] == "known_violation"
    assert residual_invariant["applies_to"] == ["state:smtp-send-claim"]

    state_node = nodes["state:http-idempotency-key"]
    assert state_node["source"] == "backend/services/http_idempotency_authority.py"

    receipt = nodes["db:table:http_idempotency_receipts"]
    assert receipt["tenant_associated"] is False

    assert (
        "py:backend.middleware.idempotency",
        "py:backend.services.http_idempotency_authority",
        "uses",
    ) in edges
    assert (
        "py:backend.services.http_idempotency_authority",
        "state:http-idempotency-key",
        "owns_state",
    ) in edges
    assert (
        "state:http-idempotency-key",
        "db:table:http_idempotency_receipts",
        "persisted_in",
    ) in edges


def test_http_idempotency_graph_closure_preserves_semantic_integrity() -> None:
    report = AUDIT.audit_graph(_graph())
    assert report["integrity"]["pass"] is True
    assert report["integrity"]["unacknowledged_blocking_findings"] == []
