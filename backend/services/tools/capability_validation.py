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
    task_id: uuid.UUID | None = None,
) -> None:
    effective_side_effect_class = side_effect_class or action.side_effect_class
    capability = _resolve_capability(
        session=session, tenant_id=tenant_id, reference=metadata.get("capability_reference")
    )
    adapter = _resolve_adapter(session=session, tenant_id=tenant_id, reference=metadata.get("adapter_reference"))

    if capability is not None:
        _validate_capability(
            capability=capability,
            action_names=_action_authority_names(action),
            side_effecting=_requires_concrete_action_scope(effective_side_effect_class),
        )
    if adapter is not None:
        _validate_adapter(
            adapter=adapter,
            action_names=_action_authority_names(action),
            side_effecting=_requires_concrete_action_scope(effective_side_effect_class),
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

    if _requires_runtime_promotion_authority(effective_side_effect_class):
        _validate_runtime_promotion_authority(
            metadata=metadata,
            action=action,
            side_effect_class=effective_side_effect_class,
            capability=capability,
            adapter=adapter,
            tenant_id=tenant_id,
            task_id=task_id,
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


def _validate_capability(*, capability: Capability, action_names: set[str], side_effecting: bool) -> None:
    supported_actions = set(capability.supported_task_types) & action_names
    required_tools = set(capability.required_tools)
    required_tool_actions = required_tools & action_names
    if "tool.invoke" not in capability.supported_task_types and not supported_actions:
        raise CapabilityActionValidationError("capability does not support tool.invoke or exact action")
    if side_effecting and not supported_actions and not required_tool_actions:
        raise CapabilityActionValidationError("capability required_tools does not include exact side-effect action")
    if capability.required_tools and "*" not in required_tools and not required_tool_actions:
        raise CapabilityActionValidationError("capability required_tools does not include exact action")


def _validate_adapter(*, adapter: CapabilityAdapter, action_names: set[str], side_effecting: bool) -> None:
    supported_actions = set(adapter.supported_task_types) & action_names
    required_tools = set(adapter.required_tools)
    required_tool_actions = required_tools & action_names
    if "tool.invoke" not in adapter.supported_task_types and not supported_actions:
        raise CapabilityActionValidationError("adapter does not support tool.invoke or exact action")
    if side_effecting and not supported_actions and not required_tool_actions:
        raise CapabilityActionValidationError("adapter required_tools does not include exact side-effect action")
    if adapter.required_tools and "*" not in required_tools and not required_tool_actions:
        raise CapabilityActionValidationError("adapter required_tools does not include exact action")


def _validate_runtime_promotion_authority(
    *,
    metadata: Mapping[str, Any],
    action: ActionDefinition,
    side_effect_class: SideEffectClass,
    capability: Capability | None,
    adapter: CapabilityAdapter | None,
    tenant_id: str,
    task_id: uuid.UUID | None,
) -> None:
    if adapter is None and capability is None:
        raise CapabilityActionValidationError("runtime promotion requires explicit capability/adapter authority")
    if _requires_exact_external_adapter_classification(side_effect_class) and adapter is None:
        raise CapabilityActionValidationError(
            "external runtime promotion requires adapter_reference with exact side_effect_classification"
        )
    if adapter is not None and not _adapter_authorizes_side_effect_class(
        classification=adapter.side_effect_classification,
        side_effect_class=side_effect_class,
    ):
        raise CapabilityActionValidationError("adapter side_effect_classification does not authorize action")
    if not side_effect_class.has_side_effect:
        return
    if side_effect_authorized(metadata, action.name, tenant_id=tenant_id, task_id=task_id):
        return
    raise CapabilityActionValidationError(
        "side-effecting action requires execution_constraints.side_effect_authorization"
    )


def _adapter_authorizes_side_effect_class(*, classification: str, side_effect_class: SideEffectClass) -> bool:
    if classification == side_effect_class.value:
        return True
    # Bridge adapters persist the canonical read-only declaration as
    # ``read_only`` while tool actions use the finer-grained ``internal_read``
    # enum. Treat the adapter declaration as an exact authority equivalent.
    if classification == "read_only" and side_effect_class == SideEffectClass.INTERNAL_READ:
        return True
    if classification in {"internal_side_effect", "idempotent_write", "non_idempotent_write"}:
        return side_effect_class.value.startswith("internal_")
    if classification == "external_side_effect":
        # Historical broad external declarations are not concrete enough for the
        # completed tool authority lane: external read/write/send/publish classes
        # must remain distinct and require exact adapter classification.
        return False
    return False


def _requires_exact_external_adapter_classification(side_effect_class: SideEffectClass) -> bool:
    return side_effect_class.value.startswith("external_")


def _requires_runtime_promotion_authority(side_effect_class: SideEffectClass) -> bool:
    return side_effect_class.has_side_effect or side_effect_class.value.startswith("external_")


def _requires_concrete_action_scope(side_effect_class: SideEffectClass) -> bool:
    return _requires_runtime_promotion_authority(side_effect_class)
