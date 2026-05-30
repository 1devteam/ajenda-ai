from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID


class CapabilityDeclaration(Protocol):
    """Capability fields required for declarative adapter compatibility checks."""

    id: UUID
    name: str
    version: str
    supported_task_types: list[str]
    risk_level: str
    enabled: bool


class CapabilityAdapterDeclaration(Protocol):
    """Adapter fields required for declarative compatibility checks."""

    capability_id: UUID | None
    capability_name: str | None
    capability_version: str | None
    supported_task_types: list[str]
    risk_level: str
    approval_requirements: dict[str, Any]
    side_effect_classification: str
    enabled: bool


class CapabilityAdapterCompatibilityError(ValueError):
    """Raised when an adapter declaration contradicts its capability contract."""


_RISK_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


def validate_capability_adapter_compatibility(
    *, adapter: CapabilityAdapterDeclaration, capability: CapabilityDeclaration
) -> None:
    """Validate a declarative adapter contract against its referenced capability.

    The checks are intentionally metadata-only. They do not register runtime
    handlers, enqueue work, invoke tools, or grant execution authority.
    """
    errors: list[str] = []

    if adapter.capability_id is not None and adapter.capability_id != capability.id:
        errors.append("capability_id does not match the resolved capability")
    if adapter.capability_name is not None and adapter.capability_name != capability.name:
        errors.append("capability_name does not match the resolved capability")
    if adapter.capability_version is not None and adapter.capability_version != capability.version:
        errors.append("capability_version does not match the resolved capability")

    unsupported_task_types = sorted(set(adapter.supported_task_types) - set(capability.supported_task_types))
    if unsupported_task_types:
        errors.append(
            "adapter supported_task_types must be a subset of the capability supported_task_types "
            f"(unsupported: {', '.join(unsupported_task_types)})"
        )

    capability_risk = _risk_rank(capability.risk_level)
    adapter_risk = _risk_rank(adapter.risk_level)
    if adapter_risk < capability_risk:
        errors.append("adapter risk_level cannot understate the referenced capability risk_level")

    if adapter.side_effect_classification == "external_side_effect" and not _approval_required(
        adapter.approval_requirements
    ):
        errors.append("external_side_effect adapters require explicit approval_requirements.required=true")

    if adapter.enabled and not capability.enabled:
        errors.append("enabled adapters cannot bind to disabled capabilities")

    if errors:
        raise CapabilityAdapterCompatibilityError("; ".join(errors))


def _risk_rank(risk_level: str) -> int:
    try:
        return _RISK_ORDER[risk_level]
    except KeyError as exc:
        raise CapabilityAdapterCompatibilityError(f"unknown risk_level: {risk_level}") from exc


def _approval_required(approval_requirements: dict[str, Any]) -> bool:
    if isinstance(approval_requirements, Mapping):
        return approval_requirements.get("required") is True
    return getattr(approval_requirements, "required", False) is True
