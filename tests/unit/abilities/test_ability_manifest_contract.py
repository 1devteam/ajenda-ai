from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.services.abilities.manifest import AbilityManifest, AbilityRiskLevel
from backend.services.tools.schemas import SideEffectClass


def _manifest(**overrides: object) -> AbilityManifest:
    payload: dict[str, object] = {
        "ability_id": "record-search",
        "display_name": "Record Search",
        "action_name": "record.search",
        "provider": "local_records",
        "capability_name": "records",
        "capability_version": "1",
        "adapter_name": "local-records",
        "adapter_version": "1",
        "input_schema_ref": "backend.services.tools.schemas.RecordSearchInput",
        "output_schema_ref": "backend.services.tools.schemas.ActionResult",
        "side_effect_class": SideEffectClass.INTERNAL_READ,
        "risk_level": AbilityRiskLevel.LOW,
        "required_permissions": ["records:read"],
        "required_tools": ["record.search"],
        "approval_required": False,
        "idempotency_required": False,
        "evidence_required": True,
        "evidence_expectations": ("action_result_evidence",),
        "readback_required": False,
        "enabled_by_default": False,
    }
    payload.update(overrides)
    return AbilityManifest.model_validate(payload)


def test_manifest_accepts_strict_runtime_ability_contract() -> None:
    manifest = _manifest(action_name=" record.search ", required_permissions=[" records:read "])

    assert manifest.action_name == "record.search"
    assert manifest.required_permissions == ["records:read"]
    assert manifest.evidence_required is True


def test_manifest_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _manifest(unexpected=True)


def test_side_effecting_manifest_requires_approval() -> None:
    with pytest.raises(ValueError, match="approval_required"):
        _manifest(
            action_name="record.write",
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
            approval_required=False,
            readback_required=True,
        )


def test_external_write_manifest_requires_idempotency() -> None:
    with pytest.raises(ValueError, match="idempotency_required"):
        _manifest(
            action_name="http.request",
            provider="http",
            side_effect_class=SideEffectClass.EXTERNAL_WRITE,
            approval_required=True,
            idempotency_required=False,
            readback_required=True,
        )


def test_runtime_manifest_requires_evidence() -> None:
    with pytest.raises(ValueError, match="evidence_required"):
        _manifest(evidence_required=False)


def test_write_manifest_requires_readback_or_deferred_reason() -> None:
    with pytest.raises(ValueError, match="readback_required"):
        _manifest(
            action_name="calendar.create_event",
            provider="local_calendar",
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
            approval_required=True,
            readback_required=False,
            readback_deferred_reason=None,
        )

    manifest = _manifest(
        action_name="calendar.create_event",
        provider="local_calendar",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        approval_required=True,
        readback_required=False,
        readback_deferred_reason="local reference provider readback is deferred to production adapter",
    )

    assert manifest.readback_deferred_reason is not None


def test_high_risk_manifest_cannot_be_enabled_by_default() -> None:
    with pytest.raises(ValueError, match="enabled by default"):
        _manifest(
            risk_level=AbilityRiskLevel.HIGH,
            enabled_by_default=True,
        )


def test_max_side_effect_class_drives_policy_for_dynamic_actions() -> None:
    with pytest.raises(ValueError, match="approval_required"):
        _manifest(
            action_name="http.request",
            provider="http",
            side_effect_class=SideEffectClass.EXTERNAL_READ,
            max_side_effect_class=SideEffectClass.EXTERNAL_WRITE,
            approval_required=False,
            idempotency_required=True,
            idempotency_contract_ref="docs/product/ability-rollout-contract.md#unit",
            readback_required=True,
        )

    with pytest.raises(ValueError, match="idempotency_required"):
        _manifest(
            action_name="http.request",
            provider="http",
            side_effect_class=SideEffectClass.EXTERNAL_READ,
            max_side_effect_class=SideEffectClass.EXTERNAL_WRITE,
            approval_required=True,
            idempotency_required=False,
            readback_required=True,
        )


def test_max_side_effect_class_cannot_understate_default_side_effect() -> None:
    with pytest.raises(ValueError, match="cannot be lower"):
        _manifest(
            action_name="record.write",
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
            max_side_effect_class=SideEffectClass.INTERNAL_READ,
            approval_required=True,
            readback_required=True,
        )


def test_blank_readback_deferred_reason_is_rejected_for_write_manifest() -> None:
    with pytest.raises(ValueError, match="readback_required"):
        _manifest(
            action_name="record.write",
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
            approval_required=True,
            readback_required=False,
            readback_deferred_reason="   ",
        )
