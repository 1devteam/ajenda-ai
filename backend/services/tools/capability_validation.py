from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository
from backend.services.capability_adapter_compatibility import (
    CapabilityAdapterDeclaration,
    validate_capability_adapter_compatibility,
)
from backend.services.tools.action_registry import ActionDefinition


@dataclass(frozen=True, slots=True)
class CapabilityActionValidationResult:
    capability_id: str | None
    adapter_id: str | None
    warnings: tuple[str, ...] = ()


def validate_capability_action_references(
    *,
    session: Session,
    tenant_id: str,
    task_type: str,
    action: ActionDefinition,
    capability_reference: Any,
    adapter_reference: Any,
) -> CapabilityActionValidationResult:
    """Validate declarative capability/adapter references without granting runtime authority."""

    capability = _resolve_capability(session=session, tenant_id=tenant_id, reference=capability_reference)
    adapter = _resolve_adapter(session=session, tenant_id=tenant_id, reference=adapter_reference)
    warnings: list[str] = []

    if capability is not None:
        if not capability.enabled:
            raise ValueError("referenced capability is disabled")
        _validate_task_or_tool_allowed(
            label="capability",
            supported_task_types=capability.supported_task_types,
            required_tools=capability.required_tools,
            task_type=task_type,
            action=action,
        )
    if adapter is not None:
        if not adapter.enabled:
            raise ValueError("referenced capability adapter is disabled")
        _validate_task_or_tool_allowed(
            label="adapter",
            supported_task_types=adapter.supported_task_types,
            required_tools=adapter.required_tools,
            task_type=task_type,
            action=action,
        )
    if capability is not None and adapter is not None:
        validate_capability_adapter_compatibility(
            capability=capability,
            adapter=CapabilityAdapterDeclaration(
                capability_id=adapter.capability_id,
                capability_name=adapter.capability_name,
                capability_version=adapter.capability_version,
                supported_task_types=adapter.supported_task_types,
                risk_level=adapter.risk_level,
                approval_requirements=adapter.approval_requirements,
                side_effect_classification=adapter.side_effect_classification,
                enabled=adapter.enabled,
            ),
        )
    if capability is None and adapter is None:
        warnings.append("no capability or adapter reference supplied")
    return CapabilityActionValidationResult(
        capability_id=str(capability.id) if capability is not None else None,
        adapter_id=str(adapter.id) if adapter is not None else None,
        warnings=tuple(warnings),
    )


def _resolve_capability(*, session: Session, tenant_id: str, reference: Any) -> Capability | None:
    if not isinstance(reference, dict) or not reference:
        return None
    repo = CapabilityRepository(session)
    raw_id = reference.get("capability_id")
    if raw_id is not None:
        try:
            capability_id = uuid.UUID(str(raw_id))
        except ValueError as exc:
            raise ValueError("capability_reference.capability_id must be a UUID") from exc
        capability = repo.get_visible_for_tenant(capability_id=capability_id, tenant_id=tenant_id)
        if capability is None:
            raise ValueError("referenced capability is not visible to tenant")
        return capability
    name = reference.get("capability_name")
    version = reference.get("capability_version")
    if isinstance(name, str) and isinstance(version, str):
        capability = repo.get_visible_by_name_version(name=name, version=version, tenant_id=tenant_id)
        if capability is None:
            raise ValueError("referenced capability name/version is not visible to tenant")
        return capability
    return None


def _resolve_adapter(*, session: Session, tenant_id: str, reference: Any) -> CapabilityAdapter | None:
    if not isinstance(reference, dict) or not reference:
        return None
    raw_id = reference.get("adapter_id") or reference.get("capability_adapter_id")
    if raw_id is None:
        return None
    try:
        adapter_id = uuid.UUID(str(raw_id))
    except ValueError as exc:
        raise ValueError("adapter_reference.adapter_id must be a UUID") from exc
    adapter = CapabilityAdapterRepository(session).get_visible_for_tenant(adapter_id=adapter_id, tenant_id=tenant_id)
    if adapter is None:
        raise ValueError("referenced capability adapter is not visible to tenant")
    return adapter


def _validate_task_or_tool_allowed(
    *,
    label: str,
    supported_task_types: list[str],
    required_tools: list[str],
    task_type: str,
    action: ActionDefinition,
) -> None:
    task_candidates = {task_type, action.name, *action.aliases}
    if supported_task_types and not (set(supported_task_types) & task_candidates):
        raise ValueError(f"{label} does not support task_type or action")
    tool_candidates = {action.name, *action.aliases, *(action.required_tools or ())}
    if required_tools and not (set(required_tools) & tool_candidates):
        raise ValueError(f"{label} required_tools do not allow action")
