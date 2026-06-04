from __future__ import annotations

import uuid

import pytest

from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository
from backend.services.tools.action_registry import ActionDefinition
from backend.services.tools.capability_validation import (
    CapabilityActionValidationError,
    validate_capability_action_authority,
)
from backend.services.tools.schemas import ActionResult, ActionRuntimeContext, SideEffectClass, ToolInvocation


def _handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    return ActionResult(action="record.search", provider="test", output={}, summary="done")


def _action(name: str = "record.search", side_effect_class: SideEffectClass = SideEffectClass.NONE) -> ActionDefinition:
    return ActionDefinition(name=name, handler=_handler, side_effect_class=side_effect_class)


def _capability(
    *, enabled: bool = True, supported: list[str] | None = None, tools: list[str] | None = None
) -> Capability:
    return Capability(
        id=uuid.uuid4(),
        tenant_id="tenant",
        name="sales_capability",
        version="1.0.0",
        description="Sales capability",
        supported_task_types=supported if supported is not None else ["tool.invoke"],
        required_tools=tools if tools is not None else ["record.search"],
        risk_level="medium",
        enabled=enabled,
    )


def _adapter(
    capability: Capability, *, enabled: bool = True, supported: list[str] | None = None, tools: list[str] | None = None
) -> CapabilityAdapter:
    return CapabilityAdapter(
        id=uuid.uuid4(),
        tenant_id="tenant",
        name="sales_adapter",
        version="1.0.0",
        capability_id=capability.id,
        capability_name=capability.name,
        capability_version=capability.version,
        supported_task_types=supported if supported is not None else ["tool.invoke"],
        required_tools=tools if tools is not None else ["record.search"],
        risk_level="medium",
        enabled=enabled,
    )


def test_validation_allows_missing_reference_for_no_side_effect_action() -> None:
    validate_capability_action_authority(session=object(), tenant_id="tenant", metadata={}, action=_action())


def test_validation_rejects_missing_reference_for_side_effect_action() -> None:
    with pytest.raises(CapabilityActionValidationError, match="explicit capability/adapter authority"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={},
            action=_action("record.write", SideEffectClass.INTERNAL_WRITE),
        )


def test_validation_accepts_exact_action_supported_by_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    capability = _capability(supported=["record.search"], tools=[])
    monkeypatch.setattr(
        CapabilityRepository, "get_visible_for_tenant", lambda self, *, capability_id, tenant_id: capability
    )

    validate_capability_action_authority(
        session=object(),
        tenant_id="tenant",
        metadata={"capability_reference": {"capability_id": str(capability.id)}},
        action=_action(),
    )


def test_validation_accepts_broad_tool_invoke_and_required_exact_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["record.search"])
    monkeypatch.setattr(
        CapabilityRepository, "get_visible_for_tenant", lambda self, *, capability_id, tenant_id: capability
    )

    validate_capability_action_authority(
        session=object(),
        tenant_id="tenant",
        metadata={"capability_reference": {"capability_id": str(capability.id)}},
        action=_action(),
    )


def test_validation_rejects_unsupported_action(monkeypatch: pytest.MonkeyPatch) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["sales.qualify"])
    monkeypatch.setattr(
        CapabilityRepository, "get_visible_for_tenant", lambda self, *, capability_id, tenant_id: capability
    )

    with pytest.raises(CapabilityActionValidationError, match="required_tools"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={"capability_reference": {"capability_id": str(capability.id)}},
            action=_action(),
        )


def test_validation_rejects_disabled_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    capability = _capability(enabled=False)
    monkeypatch.setattr(
        CapabilityRepository, "get_visible_for_tenant", lambda self, *, capability_id, tenant_id: capability
    )

    with pytest.raises(CapabilityActionValidationError, match="disabled"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={"capability_reference": {"capability_id": str(capability.id)}},
            action=_action(),
        )


def test_validation_rejects_disabled_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    capability = _capability()
    adapter = _adapter(capability, enabled=False)
    monkeypatch.setattr(
        CapabilityRepository, "get_visible_for_tenant", lambda self, *, capability_id, tenant_id: capability
    )
    monkeypatch.setattr(
        CapabilityAdapterRepository, "get_visible_for_tenant", lambda self, *, adapter_id, tenant_id: adapter
    )

    with pytest.raises(CapabilityActionValidationError, match="adapter_reference is disabled"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={
                "capability_reference": {"capability_id": str(capability.id)},
                "adapter_reference": {"adapter_id": str(adapter.id)},
            },
            action=_action(),
        )
