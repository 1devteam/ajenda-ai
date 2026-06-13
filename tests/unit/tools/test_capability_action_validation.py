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


def test_validation_accepts_registered_alias_in_required_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["crm.research"])
    monkeypatch.setattr(
        CapabilityRepository, "get_visible_for_tenant", lambda self, *, capability_id, tenant_id: capability
    )

    validate_capability_action_authority(
        session=object(),
        tenant_id="tenant",
        metadata={"capability_reference": {"capability_id": str(capability.id)}},
        action=ActionDefinition(
            name="sales.research",
            handler=_handler,
            aliases=("crm.research",),
        ),
    )


def test_side_effect_authorization_without_capability_or_adapter_still_fails() -> None:
    with pytest.raises(CapabilityActionValidationError, match="explicit capability/adapter authority"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={
                "execution_constraints": {
                    "side_effect_authorization": {
                        "schema_version": 1,
                        "allowed_actions": ["record.write"],
                        "reason": "test",
                        "approved_by": "test",
                    }
                }
            },
            action=_action("record.write", SideEffectClass.INTERNAL_WRITE),
        )


def test_side_effect_authorization_does_not_bypass_adapter_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["record.write"])
    adapter = _adapter(capability, supported=["tool.invoke"], tools=["record.write"])
    adapter.side_effect_classification = "none"

    monkeypatch.setattr(
        CapabilityRepository,
        "get_visible_for_tenant",
        lambda self, *, capability_id, tenant_id: capability,
    )
    monkeypatch.setattr(
        CapabilityAdapterRepository,
        "get_visible_for_tenant",
        lambda self, *, adapter_id, tenant_id: adapter,
    )

    with pytest.raises(CapabilityActionValidationError, match="side_effect_classification"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={
                "capability_reference": {"capability_id": str(capability.id)},
                "adapter_reference": {"adapter_id": str(adapter.id)},
                "execution_constraints": {
                    "side_effect_authorization": {
                        "schema_version": 1,
                        "allowed_actions": ["record.write"],
                        "reason": "test",
                        "approved_by": "test",
                    }
                },
            },
            action=_action("record.write", SideEffectClass.INTERNAL_WRITE),
        )


def test_adapter_internal_side_effect_rejects_webhook_external_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["webhook.dispatch"])
    adapter = _adapter(capability, supported=["tool.invoke"], tools=["webhook.dispatch"])
    adapter.side_effect_classification = "internal_side_effect"

    monkeypatch.setattr(
        CapabilityAdapterRepository,
        "get_visible_for_tenant",
        lambda self, *, adapter_id, tenant_id: adapter,
    )

    with pytest.raises(CapabilityActionValidationError, match="side_effect_classification"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={
                "adapter_reference": {"adapter_id": str(adapter.id)},
                "execution_constraints": {
                    "side_effect_authorization": {
                        "schema_version": 1,
                        "allowed_actions": ["webhook.dispatch"],
                        "reason": "test",
                        "approved_by": "test",
                    }
                },
            },
            action=_action("webhook.dispatch", SideEffectClass.EXTERNAL_SEND),
        )


def test_side_effecting_action_rejects_broad_tool_invoke_without_concrete_tool_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = _capability(supported=["tool.invoke"], tools=[])
    monkeypatch.setattr(
        CapabilityRepository,
        "get_visible_for_tenant",
        lambda self, *, capability_id, tenant_id: capability,
    )

    with pytest.raises(CapabilityActionValidationError, match="exact side-effect action"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={
                "capability_reference": {"capability_id": str(capability.id)},
                "execution_constraints": {
                    "side_effect_authorization": {
                        "schema_version": 1,
                        "allowed_actions": ["record.write"],
                        "reason": "test",
                        "approved_by": "test",
                    }
                },
            },
            action=_action("record.write", SideEffectClass.INTERNAL_WRITE),
        )


def test_side_effecting_action_accepts_exact_supported_task_type_without_required_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = _capability(supported=["record.write"], tools=[])
    monkeypatch.setattr(
        CapabilityRepository,
        "get_visible_for_tenant",
        lambda self, *, capability_id, tenant_id: capability,
    )

    validate_capability_action_authority(
        session=object(),
        tenant_id="tenant",
        metadata={
            "capability_reference": {"capability_id": str(capability.id)},
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["record.write"],
                    "reason": "test",
                    "approved_by": "test",
                }
            },
        },
        action=_action("record.write", SideEffectClass.INTERNAL_WRITE),
    )


def test_side_effecting_action_rejects_broad_adapter_without_concrete_tool_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["*"])
    adapter = _adapter(capability, supported=["tool.invoke"], tools=[])
    adapter.side_effect_classification = "internal_side_effect"

    monkeypatch.setattr(
        CapabilityAdapterRepository,
        "get_visible_for_tenant",
        lambda self, *, adapter_id, tenant_id: adapter,
    )

    with pytest.raises(CapabilityActionValidationError, match="exact side-effect action"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={
                "adapter_reference": {"adapter_id": str(adapter.id)},
                "execution_constraints": {
                    "side_effect_authorization": {
                        "schema_version": 1,
                        "allowed_actions": ["record.write"],
                        "reason": "test",
                        "approved_by": "test",
                    }
                },
            },
            action=_action("record.write", SideEffectClass.INTERNAL_WRITE),
        )


def test_side_effect_authorization_rejects_top_level_envelope() -> None:
    from backend.services.tools.schemas import side_effect_authorized

    assert (
        side_effect_authorized(
            {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["record.write"],
                    "reason": "test",
                    "approved_by": "test",
                }
            },
            "record.write",
        )
        is False
    )


@pytest.mark.parametrize("classification", ["idempotent_write", "non_idempotent_write"])
def test_adapter_write_classifications_authorize_internal_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    classification: str,
) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["record.write"])
    adapter = _adapter(capability, supported=["tool.invoke"], tools=["record.write"])
    adapter.side_effect_classification = classification

    monkeypatch.setattr(
        CapabilityAdapterRepository,
        "get_visible_for_tenant",
        lambda self, *, adapter_id, tenant_id: adapter,
    )

    validate_capability_action_authority(
        session=object(),
        tenant_id="tenant",
        metadata={
            "adapter_reference": {"adapter_id": str(adapter.id)},
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["record.write"],
                    "reason": "unit test authorization",
                    "approved_by": "qa",
                }
            },
        },
        action=_action("record.write", SideEffectClass.INTERNAL_WRITE),
    )


@pytest.mark.parametrize("classification", ["idempotent_write", "non_idempotent_write"])
def test_adapter_write_classifications_reject_external_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    classification: str,
) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["webhook.dispatch"])
    adapter = _adapter(capability, supported=["tool.invoke"], tools=["webhook.dispatch"])
    adapter.side_effect_classification = classification

    monkeypatch.setattr(
        CapabilityAdapterRepository,
        "get_visible_for_tenant",
        lambda self, *, adapter_id, tenant_id: adapter,
    )

    with pytest.raises(CapabilityActionValidationError, match="side_effect_classification"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={
                "adapter_reference": {"adapter_id": str(adapter.id)},
                "execution_constraints": {
                    "side_effect_authorization": {
                        "schema_version": 1,
                        "allowed_actions": ["webhook.dispatch"],
                        "reason": "unit test authorization",
                        "approved_by": "qa",
                    }
                },
            },
            action=_action("webhook.dispatch", SideEffectClass.EXTERNAL_SEND),
        )


def test_adapter_external_read_classification_does_not_authorize_external_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["http.request"])
    adapter = _adapter(capability, supported=["tool.invoke"], tools=["http.request"])
    adapter.side_effect_classification = SideEffectClass.EXTERNAL_READ.value

    monkeypatch.setattr(
        CapabilityAdapterRepository,
        "get_visible_for_tenant",
        lambda self, *, adapter_id, tenant_id: adapter,
    )

    with pytest.raises(CapabilityActionValidationError, match="side_effect_classification"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={
                "adapter_reference": {"adapter_id": str(adapter.id)},
                "execution_constraints": {
                    "side_effect_authorization": {
                        "schema_version": 1,
                        "allowed_actions": ["http.request"],
                        "reason": "unit test authorization",
                        "approved_by": "qa",
                    }
                },
            },
            action=_action("http.request", SideEffectClass.EXTERNAL_WRITE),
        )


@pytest.mark.parametrize(
    ("classification", "side_effect_class"),
    [
        (SideEffectClass.EXTERNAL_WRITE.value, SideEffectClass.EXTERNAL_SEND),
        (SideEffectClass.EXTERNAL_SEND.value, SideEffectClass.EXTERNAL_PUBLISH),
        ("external_side_effect", SideEffectClass.EXTERNAL_WRITE),
    ],
)
def test_external_adapter_classifications_must_match_effective_side_effect_exactly(
    monkeypatch: pytest.MonkeyPatch,
    classification: str,
    side_effect_class: SideEffectClass,
) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["external.action"])
    adapter = _adapter(capability, supported=["tool.invoke"], tools=["external.action"])
    adapter.side_effect_classification = classification

    monkeypatch.setattr(
        CapabilityAdapterRepository,
        "get_visible_for_tenant",
        lambda self, *, adapter_id, tenant_id: adapter,
    )

    with pytest.raises(CapabilityActionValidationError, match="side_effect_classification"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={
                "adapter_reference": {"adapter_id": str(adapter.id)},
                "execution_constraints": {
                    "side_effect_authorization": {
                        "schema_version": 1,
                        "allowed_actions": ["external.action"],
                        "reason": "unit test authorization",
                        "approved_by": "qa",
                    }
                },
            },
            action=_action("external.action", side_effect_class),
        )


def test_external_adapter_classification_accepts_exact_effective_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["webhook.dispatch"])
    adapter = _adapter(capability, supported=["tool.invoke"], tools=["webhook.dispatch"])
    adapter.side_effect_classification = SideEffectClass.EXTERNAL_SEND.value

    monkeypatch.setattr(
        CapabilityAdapterRepository,
        "get_visible_for_tenant",
        lambda self, *, adapter_id, tenant_id: adapter,
    )

    validate_capability_action_authority(
        session=object(),
        tenant_id="tenant",
        metadata={
            "adapter_reference": {"adapter_id": str(adapter.id)},
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["webhook.dispatch"],
                    "reason": "unit test authorization",
                    "approved_by": "qa",
                }
            },
        },
        action=_action("webhook.dispatch", SideEffectClass.EXTERNAL_SEND),
    )


@pytest.mark.parametrize(
    ("action_name", "side_effect_class"),
    [
        ("http.request", SideEffectClass.EXTERNAL_READ),
        ("http.request", SideEffectClass.EXTERNAL_WRITE),
        ("webhook.dispatch", SideEffectClass.EXTERNAL_SEND),
        ("external.publish", SideEffectClass.EXTERNAL_PUBLISH),
    ],
)
def test_external_actions_reject_capability_only_promotion_authority(
    monkeypatch: pytest.MonkeyPatch,
    action_name: str,
    side_effect_class: SideEffectClass,
) -> None:
    capability = _capability(supported=["tool.invoke"], tools=[action_name])

    monkeypatch.setattr(
        CapabilityRepository,
        "get_visible_for_tenant",
        lambda self, *, capability_id, tenant_id: capability,
    )

    metadata = {
        "capability_reference": {"capability_id": str(capability.id)},
        "execution_constraints": {
            "side_effect_authorization": {
                "schema_version": 1,
                "allowed_actions": [action_name],
                "reason": "unit test authorization",
                "approved_by": "qa",
            }
        },
    }

    with pytest.raises(CapabilityActionValidationError, match="requires adapter_reference"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata=metadata,
            action=_action(action_name, side_effect_class),
        )


def test_external_read_requires_runtime_promotion_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["http.request"])
    adapter = _adapter(capability, supported=["tool.invoke"], tools=["http.request"])
    adapter.side_effect_classification = SideEffectClass.EXTERNAL_READ.value

    monkeypatch.setattr(
        CapabilityAdapterRepository,
        "get_visible_for_tenant",
        lambda self, *, adapter_id, tenant_id: adapter,
    )

    validate_capability_action_authority(
        session=object(),
        tenant_id="tenant",
        metadata={"adapter_reference": {"adapter_id": str(adapter.id)}},
        action=_action("http.request", SideEffectClass.EXTERNAL_READ),
    )


def test_external_side_effect_does_not_authorize_external_read(monkeypatch: pytest.MonkeyPatch) -> None:
    capability = _capability(supported=["tool.invoke"], tools=["http.request"])
    adapter = _adapter(capability, supported=["tool.invoke"], tools=["http.request"])
    adapter.side_effect_classification = "external_side_effect"

    monkeypatch.setattr(
        CapabilityAdapterRepository,
        "get_visible_for_tenant",
        lambda self, *, adapter_id, tenant_id: adapter,
    )

    with pytest.raises(CapabilityActionValidationError, match="side_effect_classification"):
        validate_capability_action_authority(
            session=object(),
            tenant_id="tenant",
            metadata={"adapter_reference": {"adapter_id": str(adapter.id)}},
            action=_action("http.request", SideEffectClass.EXTERNAL_READ),
        )
