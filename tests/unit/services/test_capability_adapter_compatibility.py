from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from backend.services.capability_adapter_compatibility import (
    CapabilityAdapterCompatibilityError,
    CapabilityAdapterDeclaration,
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


def _adapter(**overrides: object) -> CapabilityAdapterDeclaration:
    capability_id = uuid.uuid4()
    values: dict[str, object] = {
        "capability_id": capability_id,
        "capability_name": "crm-record-review",
        "capability_version": "1.0.0",
        "supported_task_types": ["crm.review"],
        "risk_level": "medium",
        "approval_requirements": {"required": False, "approver_roles": [], "conditions": []},
        "side_effect_classification": "read_only",
        "enabled": True,
    }
    values.update(overrides)
    return CapabilityAdapterDeclaration(**values)  # type: ignore[arg-type]


def test_compatible_adapter_declaration_passes_without_side_effects() -> None:
    capability_id = uuid.uuid4()
    capability = _capability(id=capability_id)
    adapter = _adapter(capability_id=capability_id)

    validate_capability_adapter_compatibility(capability=capability, adapter=adapter)


def test_supported_task_types_must_be_declared_by_capability() -> None:
    capability_id = uuid.uuid4()
    capability = _capability(id=capability_id, supported_task_types=["crm.review"])
    adapter = _adapter(capability_id=capability_id, supported_task_types=["crm.review", "crm.email"])

    with pytest.raises(CapabilityAdapterCompatibilityError, match="supported_task_types"):
        validate_capability_adapter_compatibility(capability=capability, adapter=adapter)


def test_adapter_risk_cannot_understate_capability_risk() -> None:
    capability_id = uuid.uuid4()
    capability = _capability(id=capability_id, risk_level="high")
    adapter = _adapter(capability_id=capability_id, risk_level="medium")

    with pytest.raises(CapabilityAdapterCompatibilityError, match="risk_level cannot understate"):
        validate_capability_adapter_compatibility(capability=capability, adapter=adapter)


def test_external_side_effect_requires_approval() -> None:
    capability_id = uuid.uuid4()
    capability = _capability(id=capability_id)
    adapter = _adapter(capability_id=capability_id, side_effect_classification="external_side_effect")

    with pytest.raises(CapabilityAdapterCompatibilityError, match="external_side_effect"):
        validate_capability_adapter_compatibility(capability=capability, adapter=adapter)


def test_enabled_adapter_cannot_bind_to_disabled_capability() -> None:
    capability_id = uuid.uuid4()
    capability = _capability(id=capability_id, enabled=False)
    adapter = _adapter(capability_id=capability_id, enabled=True)

    with pytest.raises(CapabilityAdapterCompatibilityError, match="disabled capability"):
        validate_capability_adapter_compatibility(capability=capability, adapter=adapter)
