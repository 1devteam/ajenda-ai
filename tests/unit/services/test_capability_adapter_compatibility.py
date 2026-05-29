from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from backend.services.capability_adapter_compatibility import (
    CapabilityAdapterCompatibilityError,
    validate_capability_adapter_compatibility,
)


def _capability(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "crm-record-review",
        "version": "1.0.0",
        "supported_task_types": ["crm.review", "crm.summarize"],
        "risk_level": "medium",
        "enabled": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _adapter(capability: SimpleNamespace, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "capability_id": capability.id,
        "capability_name": capability.name,
        "capability_version": capability.version,
        "supported_task_types": ["crm.review"],
        "risk_level": capability.risk_level,
        "approval_requirements": {"required": False},
        "side_effect_classification": "read_only",
        "enabled": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_compatible_adapter_declaration_passes_without_runtime_side_effects() -> None:
    capability = _capability()
    adapter = _adapter(capability)

    validate_capability_adapter_compatibility(adapter=adapter, capability=capability)


def test_adapter_task_types_must_be_subset_of_capability_task_types() -> None:
    capability = _capability()
    adapter = _adapter(capability, supported_task_types=["crm.review", "crm.export"])

    with pytest.raises(CapabilityAdapterCompatibilityError, match=r"crm\.export"):
        validate_capability_adapter_compatibility(adapter=adapter, capability=capability)


def test_adapter_risk_cannot_understate_capability_risk() -> None:
    capability = _capability(risk_level="high")
    adapter = _adapter(capability, risk_level="medium")

    with pytest.raises(CapabilityAdapterCompatibilityError, match="cannot understate"):
        validate_capability_adapter_compatibility(adapter=adapter, capability=capability)


def test_external_side_effect_adapter_requires_explicit_approval() -> None:
    capability = _capability()
    adapter = _adapter(
        capability,
        side_effect_classification="external_side_effect",
        approval_requirements={"required": False},
    )

    with pytest.raises(CapabilityAdapterCompatibilityError, match="external_side_effect"):
        validate_capability_adapter_compatibility(adapter=adapter, capability=capability)


def test_enabled_adapter_cannot_bind_to_disabled_capability() -> None:
    capability = _capability(enabled=False)
    adapter = _adapter(capability, enabled=True)

    with pytest.raises(CapabilityAdapterCompatibilityError, match="disabled capabilities"):
        validate_capability_adapter_compatibility(adapter=adapter, capability=capability)


def test_adapter_binding_fields_must_match_resolved_capability() -> None:
    capability = _capability()
    adapter = _adapter(capability, capability_name="other-capability")

    with pytest.raises(CapabilityAdapterCompatibilityError, match="capability_name"):
        validate_capability_adapter_compatibility(adapter=adapter, capability=capability)
