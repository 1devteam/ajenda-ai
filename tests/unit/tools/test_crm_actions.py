from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from backend.services.tools.action_registry import ActionRegistry, get_default_action_registry
from backend.services.tools.crm_actions import register_crm_actions
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id="tenant-crm-test",
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
    )


def test_crm_observe_is_registered_and_returns_tenant_scoped_evidence() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(action="crm.observe", input={"record_type": "contact", "limit": 5}),
        _context(),
    )

    assert result.provider == "ajenda_crm"
    assert result.side_effect_class.value == "internal_read"
    assert result.output["count"] == len(result.output["observations"])
    assert result.evidence[0].tenant_id == "tenant-crm-test"


def test_crm_reconcile_prepares_without_execution_authority() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="crm.reconcile",
            input={
                "desired_state": {
                    "canonical_entity_id": "company:acme.example",
                    "object_type": "account",
                    "lifecycle_state": "resolved",
                    "fields": {"name": "Acme"},
                    "source_artifact_ids": ["artifact-1"],
                },
                "identity_decision": {
                    "decision_status": "matched",
                    "candidate_ids": ["candidate-1"],
                    "canonical_entity_id": "company:acme.example",
                    "supporting_evidence_ids": ["evidence-1"],
                    "rule_version": "1.0.0",
                    "decided_by": "identity.resolve_company",
                },
            },
        ),
        _context(),
    )

    assert result.side_effect_class.value == "none"
    assert result.output["grants_execution_authority"] is False
    assert result.output["reconciliation_plan"]["operation"]["operation_kind"] == "create"


def test_crm_actions_are_in_default_registry() -> None:
    registry = ActionRegistry()
    register_crm_actions(registry)
    assert {"crm.observe", "crm.reconcile", "crm.verify_effect"} <= set(registry.actions)


def _verify_input(*, certainty: str = "verified", matching: bool = True) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    observation = {
        "provider": "ajenda_internal",
        "provider_account_id": "tenant-crm-test",
        "provider_record_id": "account-1",
        "canonical_entity_id": "company:acme.example",
        "object_type": "account",
        "lifecycle_state": "resolved",
        "fields": {"name": "Acme" if matching else "Other"},
        "association_entity_ids": [],
        "provider_version": "record:account-1",
        "observed_at_iso": now,
    }
    receipt = {
        "provider": "ajenda_internal",
        "provider_account_id": "tenant-crm-test",
        "action_name": "crm.mutate",
        "idempotency_key": "effect-1",
        "request_hash": "sha256:" + "a" * 64,
        "attempted_at": now,
        "certainty": certainty,
        "provider_object_ids": ["account-1"],
        "read_back_at": now if certainty == "verified" else None,
        "read_back_hash": "sha256:" + "b" * 64 if certainty == "verified" else None,
    }
    return {
        "desired_state": {
            "canonical_entity_id": "company:acme.example",
            "object_type": "account",
            "lifecycle_state": "resolved",
            "fields": {"name": "Acme"},
            "source_artifact_ids": ["artifact-1"],
        },
        "effect_receipt": receipt,
        "readback_observation": observation,
    }


def test_crm_verify_effect_confirms_matching_readback_without_authority() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(action="crm.verify_effect", input=_verify_input()),
        _context(),
    )

    assert result.side_effect_class.value == "internal_read"
    assert result.output["verified"] is True
    assert result.output["grants_execution_authority"] is False
    assert result.evidence[0].tenant_id == "tenant-crm-test"


def test_crm_verify_effect_reports_mismatched_readback() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(action="crm.verify_effect", input=_verify_input(matching=False)),
        _context(),
    )

    assert result.output["verified"] is False
    assert "read-back state does not equal desired canonical state" in result.output["reasons"]


def test_crm_verify_effect_rejects_cross_tenant_receipt() -> None:
    payload = _verify_input()
    payload["effect_receipt"]["provider_account_id"] = "other-tenant"  # type: ignore[index]
    registry = get_default_action_registry(rebuild=True)

    with pytest.raises(ValueError, match="does not match runtime tenant"):
        registry.invoke(ToolInvocation(action="crm.verify_effect", input=payload), _context())
