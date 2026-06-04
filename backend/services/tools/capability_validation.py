from __future__ import annotations

import uuid
from collections.abc import Mapping
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
from backend.services.tools.schemas import SideEffectClass, side_effect_authorized


class CapabilityActionValidationError(ValueError):
    pass


def validate_capability_action_authority(
    *,
    session: Session,
    tenant_id: str,
    metadata: Mapping[str, Any],
    action: ActionDefinition,
    side_effect_class: SideEffectClass | None = None,
) -> None:
    effective_side_effect_class = side_effect_class or action.side_effect_class
    capability = _resolve_capability(
        session=session, tenant_id=tenant_id, reference=metadata.get("capability_reference")
    )
    adapter = _resolve_adapter(session=session, tenant_id=tenant_id, reference=metadata.get("adapter_reference"))

    if capability is not None:
        _validate_capability(capability=capability, action_names=_action_authority_names(action))
    if adapter is not None:
        _validate_adapter(adapter=adapter, action_names=_action_authority_names(action))
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

    if effective_side_effect_class.has_side_effect:
        _validate_side_effect_authority(
            metadata=metadata,
            action=action,
            side_effect_class=effective_side_effect_class,
            capability=capability,
            adapter=adapter,
        )


def _resolve_capability(*, session: Session, tenant_id: str, reference: object) -> Capability | None:
    if reference is None:
        return None
    if not isinstance(reference, Mapping):
        raise CapabilityActionValidationError("capability_reference must be an object")
    repo = CapabilityRepository(session)
    if reference.get("capability_id"):
        capability = repo.get_visible_for_tenant(
            capability_id=uuid.UUID(str(reference["capability_id"])), tenant_id=tenant_id
        )
    elif reference.get("name") and reference.get("version"):
        capability = repo.get_visible_by_name_version(
            name=str(reference["name"]), version=str(reference["version"]), tenant_id=tenant_id
        )
    else:
        raise CapabilityActionValidationError("capability_reference requires capability_id or name/version")
    if capability is None:
        raise CapabilityActionValidationError("capability_reference is not visible for tenant")
    if not capability.enabled:
        raise CapabilityActionValidationError("capability_reference is disabled")
    return capability


def _resolve_adapter(*, session: Session, tenant_id: str, reference: object) -> CapabilityAdapter | None:
    if reference is None:
        return None
    if not isinstance(reference, Mapping):
        raise CapabilityActionValidationError("adapter_reference must be an object")
    if not reference.get("adapter_id"):
        raise CapabilityActionValidationError("adapter_reference requires adapter_id")
    adapter = CapabilityAdapterRepository(session).get_visible_for_tenant(
        adapter_id=uuid.UUID(str(reference["adapter_id"])), tenant_id=tenant_id
    )
    if adapter is None:
        raise CapabilityActionValidationError("adapter_reference is not visible for tenant")
    if not adapter.enabled:
        raise CapabilityActionValidationError("adapter_reference is disabled")
    return adapter


def _action_authority_names(action: ActionDefinition) -> set[str]:
    return {action.name, *action.aliases}


def _validate_capability(*, capability: Capability, action_names: set[str]) -> None:
    if "tool.invoke" not in capability.supported_task_types and not (
        set(capability.supported_task_types) & action_names
    ):
        raise CapabilityActionValidationError("capability does not support tool.invoke or exact action")
    if (
        capability.required_tools
        and "*" not in capability.required_tools
        and not (set(capability.required_tools) & action_names)
    ):
        raise CapabilityActionValidationError("capability required_tools does not include exact action")


def _validate_adapter(*, adapter: CapabilityAdapter, action_names: set[str]) -> None:
    if "tool.invoke" not in adapter.supported_task_types and not (set(adapter.supported_task_types) & action_names):
        raise CapabilityActionValidationError("adapter does not support tool.invoke or exact action")
    if (
        adapter.required_tools
        and "*" not in adapter.required_tools
        and not (set(adapter.required_tools) & action_names)
    ):
        raise CapabilityActionValidationError("adapter required_tools does not include exact action")


def _validate_side_effect_authority(
    *,
    metadata: Mapping[str, Any],
    action: ActionDefinition,
    side_effect_class: SideEffectClass,
    capability: Capability | None,
    adapter: CapabilityAdapter | None,
) -> None:
    if adapter is None and capability is None:
        raise CapabilityActionValidationError("side-effecting action requires explicit capability/adapter authority")
    if side_effect_authorized(metadata, action.name):
        return
    if adapter is not None and adapter.side_effect_classification not in {
        side_effect_class.value,
        "external_side_effect",
        "internal_side_effect",
    }:
        raise CapabilityActionValidationError("adapter side_effect_classification does not authorize action")
    raise CapabilityActionValidationError(
        "side-effecting action requires execution_constraints.side_effect_authorization"
    )
