from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

RISK_RANK: dict[str, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


class CapabilityDeclaration(Protocol):
    """Capability fields required for pure adapter compatibility checks."""

    id: uuid.UUID
    name: str
    version: str
    supported_task_types: list[str]
    risk_level: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class CapabilityAdapterDeclaration:
    """Adapter fields required for pure capability compatibility checks."""

    capability_id: uuid.UUID | None
    capability_name: str | None
    capability_version: str | None
    supported_task_types: list[str]
    risk_level: str
    approval_requirements: dict[str, Any]
    side_effect_classification: str
    enabled: bool


class CapabilityAdapterCompatibilityError(ValueError):
    """Raised when a declarative adapter overstates compatibility with a capability."""


def validate_capability_adapter_compatibility(
    *, capability: CapabilityDeclaration, adapter: CapabilityAdapterDeclaration
) -> None:
    """Validate a declarative capability adapter binding without side effects.

    This guardrail is intentionally metadata-only. It does not register runtime
    handlers, enqueue work, grant execution authority, or inspect mutable state
    outside the supplied declarations.
    """
    _validate_binding_matches_capability(capability=capability, adapter=adapter)
    _validate_task_type_compatibility(capability=capability, adapter=adapter)
    _validate_risk_compatibility(capability=capability, adapter=adapter)
    _validate_side_effect_approval(adapter=adapter)
    _validate_enabled_compatibility(capability=capability, adapter=adapter)


def _validate_binding_matches_capability(
    *, capability: CapabilityDeclaration, adapter: CapabilityAdapterDeclaration
) -> None:
    if adapter.capability_id is not None and adapter.capability_id != capability.id:
        raise CapabilityAdapterCompatibilityError("adapter capability_id does not match resolved capability")
    if adapter.capability_name is not None and adapter.capability_name != capability.name:
        raise CapabilityAdapterCompatibilityError("adapter capability_name does not match resolved capability")
    if adapter.capability_version is not None and adapter.capability_version != capability.version:
        raise CapabilityAdapterCompatibilityError("adapter capability_version does not match resolved capability")


def _validate_task_type_compatibility(
    *, capability: CapabilityDeclaration, adapter: CapabilityAdapterDeclaration
) -> None:
    unsupported = sorted(set(adapter.supported_task_types) - set(capability.supported_task_types))
    if unsupported:
        joined = ", ".join(unsupported)
        raise CapabilityAdapterCompatibilityError(
            f"adapter supported_task_types must be declared by capability: {joined}"
        )


def _validate_risk_compatibility(*, capability: CapabilityDeclaration, adapter: CapabilityAdapterDeclaration) -> None:
    capability_rank = RISK_RANK.get(capability.risk_level)
    adapter_rank = RISK_RANK.get(adapter.risk_level)
    if capability_rank is None:
        raise CapabilityAdapterCompatibilityError(f"capability risk_level is unsupported: {capability.risk_level}")
    if adapter_rank is None:
        raise CapabilityAdapterCompatibilityError(f"adapter risk_level is unsupported: {adapter.risk_level}")
    if adapter_rank < capability_rank:
        raise CapabilityAdapterCompatibilityError("adapter risk_level cannot understate capability risk_level")


_APPROVAL_REQUIRED_SIDE_EFFECT_CLASSIFICATIONS = {
    "external_side_effect",
    "external_write",
    "external_send",
    "external_publish",
}


def _validate_side_effect_approval(*, adapter: CapabilityAdapterDeclaration) -> None:
    if adapter.side_effect_classification not in _APPROVAL_REQUIRED_SIDE_EFFECT_CLASSIFICATIONS:
        return
    if adapter.approval_requirements.get("required") is not True:
        raise CapabilityAdapterCompatibilityError(
            f"{adapter.side_effect_classification} adapters require approval_requirements.required"
        )


def _validate_enabled_compatibility(
    *, capability: CapabilityDeclaration, adapter: CapabilityAdapterDeclaration
) -> None:
    if adapter.enabled and not capability.enabled:
        raise CapabilityAdapterCompatibilityError("enabled adapter cannot bind to a disabled capability")
