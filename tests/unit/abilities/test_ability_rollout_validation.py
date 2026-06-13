from __future__ import annotations

import pytest

from backend.services.abilities.catalog import INTERNAL_ABILITY_MANIFESTS
from backend.services.abilities.manifest import AbilityManifest, AbilityRiskLevel
from backend.services.abilities.rollout_validation import validate_manifest_collection
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import SideEffectClass


def _manifest(**overrides: object) -> AbilityManifest:
    payload = {
        "ability_id": "unit-action",
        "display_name": "Unit Action",
        "action_name": "unit.action",
        "provider": "unit",
        "capability_name": "unit",
        "capability_version": "1",
        "adapter_name": "unit-adapter",
        "adapter_version": "1",
        "input_schema_ref": "none",
        "output_schema_ref": "backend.services.tools.schemas.ActionResult",
        "side_effect_class": SideEffectClass.NONE,
        "risk_level": AbilityRiskLevel.LOW,
        "evidence_required": True,
        "evidence_expectations": ("action_result_evidence",),
        "enabled_by_default": False,
    }
    payload.update(overrides)
    return AbilityManifest.model_validate(payload)


def test_every_canonical_registered_action_has_exactly_one_valid_manifest() -> None:
    registry = get_default_action_registry(rebuild=True)

    validate_manifest_collection(
        manifests=INTERNAL_ABILITY_MANIFESTS,
        registered_actions=registry.actions,
        require_all_registered=True,
    )

    manifest_actions = [manifest.action_name for manifest in INTERNAL_ABILITY_MANIFESTS]
    canonical_actions = {definition.name for definition in registry.actions.values()}
    assert sorted(manifest_actions) == sorted(canonical_actions)
    assert len(manifest_actions) == len(set(manifest_actions))


def test_idempotency_required_manifest_requires_contract_ref() -> None:
    with pytest.raises(ValueError, match="idempotency_contract_ref"):
        _manifest(
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
            risk_level=AbilityRiskLevel.HIGH,
            approval_required=True,
            idempotency_required=True,
            readback_deferred_reason="Provider readback is deferred in this unit test.",
        )


def test_evidence_required_manifest_requires_evidence_expectations() -> None:
    with pytest.raises(ValueError, match="evidence_expectations"):
        _manifest(evidence_expectations=())


def test_write_send_publish_manifest_requires_readback_or_deferred_reason() -> None:
    with pytest.raises(ValueError, match="readback_required"):
        _manifest(
            side_effect_class=SideEffectClass.EXTERNAL_PUBLISH,
            risk_level=AbilityRiskLevel.HIGH,
            approval_required=True,
            idempotency_required=True,
            idempotency_contract_ref="docs/product/ability-rollout-contract.md#unit",
        )


def test_approval_required_manifest_cannot_be_enabled_by_default() -> None:
    with pytest.raises(ValueError, match="approval-required"):
        _manifest(
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
            approval_required=True,
            readback_required=True,
            enabled_by_default=True,
        )


def test_external_read_manifest_requires_approval_and_cannot_be_enabled_by_default() -> None:
    with pytest.raises(ValueError, match="external abilities require approval_required"):
        _manifest(side_effect_class=SideEffectClass.EXTERNAL_READ)

    with pytest.raises(ValueError, match="external abilities cannot be enabled by default"):
        _manifest(
            side_effect_class=SideEffectClass.EXTERNAL_READ,
            approval_required=True,
            enabled_by_default=True,
        )
