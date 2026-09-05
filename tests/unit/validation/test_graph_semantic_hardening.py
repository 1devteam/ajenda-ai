from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts" / "validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

BUILD_PATH = VALIDATION_DIR / "build_dependency_graph.py"
BUILD_SPEC = importlib.util.spec_from_file_location("graph_semantic_build", BUILD_PATH)
assert BUILD_SPEC is not None and BUILD_SPEC.loader is not None
BUILD = importlib.util.module_from_spec(BUILD_SPEC)
sys.modules[BUILD_SPEC.name] = BUILD
BUILD_SPEC.loader.exec_module(BUILD)

AUDIT_PATH = VALIDATION_DIR / "graph_completeness_audit.py"
AUDIT_SPEC = importlib.util.spec_from_file_location("graph_semantic_audit", AUDIT_PATH)
assert AUDIT_SPEC is not None and AUDIT_SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(AUDIT_SPEC)
sys.modules[AUDIT_SPEC.name] = AUDIT
AUDIT_SPEC.loader.exec_module(AUDIT)

IMPACT_PATH = VALIDATION_DIR / "graph_impact_analysis.py"
IMPACT_SPEC = importlib.util.spec_from_file_location("graph_semantic_impact", IMPACT_PATH)
assert IMPACT_SPEC is not None and IMPACT_SPEC.loader is not None
IMPACT = importlib.util.module_from_spec(IMPACT_SPEC)
sys.modules[IMPACT_SPEC.name] = IMPACT
IMPACT_SPEC.loader.exec_module(IMPACT)


def _graph() -> dict:
    return BUILD.build_graph()


def test_rls_inventory_models_complete_and_missing_table_envelopes() -> None:
    graph = _graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}
    findings = {item["id"]: item for item in graph["semantic_findings"]}

    protected = nodes["db:table:tenant_internal_records"]
    assert protected["tenant_associated"] is True
    assert protected["rls_enabled"] is True
    assert protected["rls_forced"] is True
    assert protected["rls_complete"] is True

    for table in ("tenant_usage", "webhook_endpoints", "webhook_deliveries"):
        repaired = nodes[f"db:table:{table}"]
        assert repaired["tenant_associated"] is True
        assert repaired["rls_enabled"] is True
        assert repaired["rls_forced"] is True
        assert repaired["rls_complete"] is True
        assert repaired["source"] == "alembic/versions/0041_restore_tenant_rls_boundaries.py"
        assert f"rls-missing:{table}" not in findings
        assert (
            "migration:0041_restore_tenant_rls_boundaries",
            f"db:table:{table}",
            "creates_or_alters_table",
        ) in edges

    repaired_tables = {
        "rls-missing:email_send_idempotency_receipts",
        "rls-missing:mission_composition_proposals",
        "rls-missing:tenant_onboarding_states",
        "rls-missing:member_onboarding_preferences",
    }
    assert repaired_tables.isdisjoint(findings.keys())


def test_rls_inventory_preserves_explicit_cross_tenant_exceptions() -> None:
    graph = _graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    finding_ids = {item["id"] for item in graph["semantic_findings"]}

    for table in ("audit_events", "tenant_members", "stripe_webhook_events"):
        node = nodes[f"db:table:{table}"]
        assert node["rls_exempt"] is True
        assert f"rls-missing:{table}" not in finding_ids

    auth_sessions = nodes["db:table:customer_auth_sessions"]
    assert auth_sessions["rls_exempt"] is True
    assert "Authentication control-plane" in auth_sessions["rls_exempt_reason"]
    assert "rls-missing:customer_auth_sessions" not in finding_ids


def test_production_egress_is_inventory_backed_and_known_bypasses_are_visible() -> None:
    graph = _graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    findings = {item["id"]: item for item in graph["semantic_findings"]}

    authority_sink = nodes["egress:backend.services.network_egress"]
    assert authority_sink["classification"] == "governed_authority"
    assert "egress:backend.services.llm.openai_compatible" not in nodes
    assert "egress:backend.services.verification_delivery" not in nodes
    assert "egress-ungoverned:backend.services.llm.openai_compatible" not in findings
    assert "egress-ungoverned:backend.services.verification_delivery" not in findings
    assert "egress-ungoverned:backend.services.network_egress" not in findings


def test_state_ownership_resources_and_invariants_are_first_class() -> None:
    graph = _graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}
    invariants = {item["id"]: item for item in graph["invariants"]}
    finding_ids = {item["id"] for item in graph["semantic_findings"]}

    expected_state = {
        "state:redis-task-lease",
        "state:http-idempotency-key",
        "state:smtp-send-claim",
        "state:verification-token",
        "state:bootstrap-api-key",
        "state:customer-refresh-token",
        "state:api-key-quota-capacity",
    }
    assert expected_state <= nodes.keys()

    assert invariants["durable-idempotency-ownership"]["status"] == "enforced"
    assert invariants["durable-idempotency-ownership"]["applies_to"] == ["state:smtp-send-claim"]
    assert (
        "py:backend.repositories.email_send_idempotency_repository",
        "state:smtp-send-claim",
        "serializes_state",
    ) in edges
    assert "state-ownership:smtp-send-claim" not in finding_ids

    assert invariants["atomic-quota-reservation"]["status"] == "enforced"
    assert invariants["atomic-quota-reservation"]["applies_to"] == ["state:api-key-quota-capacity"]
    assert (
        "py:backend.services.quota_enforcement",
        "state:api-key-quota-capacity",
        "serializes_state",
    ) in edges
    assert nodes["state:api-key-quota-capacity"]["source"] == "backend/services/quota_enforcement.py"
    assert "state-ownership:api-key-quota-capacity" not in finding_ids

    assert invariants["lease-owner-integrity"]["status"] == "enforced"
    assert invariants["lease-owner-integrity"]["applies_to"] == ["state:redis-task-lease"]
    assert nodes["state:redis-task-lease"]["source"] == "backend/queue/adapters/redis_owner_integrity.py"
    assert "state-ownership:redis-task-lease" not in finding_ids

    assert invariants["single-use-secret-consumption"]["status"] == "enforced"
    assert invariants["single-use-secret-consumption"]["applies_to"] == [
        "state:verification-token",
        "state:bootstrap-api-key",
        "state:customer-refresh-token",
    ]


def test_semantic_finding_ratchet_has_no_unacknowledged_blockers_at_baseline() -> None:
    report = AUDIT.audit_graph(_graph())
    assert report["integrity"]["pass"] is True
    assert report["integrity"]["unacknowledged_blocking_findings"] == []
    assert report["integrity"]["semantic_finding_count"] >= 0


def test_rls_migration_change_reaches_tenant_isolation_invariant() -> None:
    report = IMPACT.analyze_impact(_graph(), ["alembic/versions/0034_add_email_send_idempotency_receipts.py"])
    changed_ids = {item["id"] for item in report["changed_nodes"]}
    invariant_ids = {item["id"] for item in report["relevant_invariants"]}

    assert "migration:0034_add_email_send_idempotency_receipts" in changed_ids
    assert "tenant-isolation" in invariant_ids


def test_rls_only_migration_change_reaches_existing_tables_and_tenant_invariant() -> None:
    report = IMPACT.analyze_impact(_graph(), ["alembic/versions/0041_restore_tenant_rls_boundaries.py"])
    changed_ids = {item["id"] for item in report["changed_nodes"]}
    invariant_ids = {item["id"] for item in report["relevant_invariants"]}

    assert "migration:0041_restore_tenant_rls_boundaries" in changed_ids
    for table in ("tenant_usage", "webhook_endpoints", "webhook_deliveries"):
        assert f"db:table:{table}" in changed_ids
    assert "tenant-isolation" in invariant_ids
