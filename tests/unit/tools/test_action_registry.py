from __future__ import annotations

import uuid

import pytest

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry, get_default_action_registry
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    CredentialReference,
    EvidenceItem,
    RuntimeCredentialMaterial,
    SideEffectClass,
    ToolInvocation,
)


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-test",
        lease_id=str(uuid.uuid4()),
    )


def _evidence(
    *,
    context: ActionRuntimeContext,
    action: str = "custom.action",
    provider: str = "test",
    side_effect_class: SideEffectClass = SideEffectClass.NONE,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="action_result",
        evidence_source=f"tool.invoke.{action}",
        action_name=action,
        tool_provider=provider,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary="custom action done",
        side_effect_class=side_effect_class,
    )


def test_action_registry_registers_and_invokes_action() -> None:
    registry = ActionRegistry()

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        return ActionResult(
            action="custom.action",
            provider="test",
            output={"echo": invocation.input},
            evidence=[_evidence(context=context)],
            summary="custom action done",
        )

    registry.register(ActionDefinition(name="custom.action", handler=handler, provider="test"))

    result = registry.invoke(ToolInvocation(action="custom.action", input={"value": 7}), _context())

    assert result.action == "custom.action"
    assert result.output == {"echo": {"value": 7}}


def test_action_registry_rejects_duplicate_action_names() -> None:
    registry = ActionRegistry()

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        return ActionResult(
            action="dup.action",
            provider="test",
            output={},
            evidence=[_evidence(context=context, action="dup.action")],
            summary="done",
        )

    registry.register(ActionDefinition(name="dup.action", handler=handler))

    with pytest.raises(ValueError, match="action already registered"):
        registry.register(ActionDefinition(name="dup.action", handler=handler))


def test_action_registry_fails_closed_on_unknown_action() -> None:
    registry = ActionRegistry()

    with pytest.raises(ValueError, match="unknown action"):
        registry.get("missing.action")


def test_default_registry_is_frozen_and_stable() -> None:
    registry = get_default_action_registry(rebuild=True)
    first_names = sorted(registry.actions)

    with pytest.raises(ValueError, match="frozen"):
        registry.register(
            ActionDefinition(
                name="late.action",
                handler=lambda invocation, context: ActionResult(
                    action="late.action",
                    provider="test",
                    output={},
                    evidence=[_evidence(context=context, action="late.action")],
                    summary="late",
                ),
            )
        )

    assert sorted(get_default_action_registry().actions) == first_names
    assert "tool.invoke" not in first_names
    assert {
        "record.search",
        "http.request",
        "webhook.dispatch",
        "calendar.create_event",
        "crm.research",
        "gtm.message_draft",
    }.issubset(first_names)


def test_action_registry_rejects_non_action_result_handler_output() -> None:
    registry = ActionRegistry()

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> object:
        return object()

    registry.register(ActionDefinition(name="bad.action", handler=handler, provider="test"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="valid ActionResult"):
        registry.invoke(ToolInvocation(action="bad.action", input={}), _context())


def test_action_registry_requires_evidence_item_scope_to_match_runtime_context() -> None:
    registry = ActionRegistry()

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        evidence = _evidence(context=context)
        evidence.tenant_id = str(uuid.uuid4())
        return ActionResult(
            action="custom.action",
            provider="test",
            output={},
            evidence=[evidence],
            summary="bad evidence scope",
        )

    registry.register(ActionDefinition(name="custom.action", handler=handler, provider="test"))

    with pytest.raises(ValueError, match="tenant_id"):
        registry.invoke(ToolInvocation(action="custom.action", input={}), _context())


def test_action_registry_requires_result_side_effect_class_to_match_resolver() -> None:
    registry = ActionRegistry()

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        return ActionResult(
            action="resolver.action",
            provider="test",
            side_effect_class=SideEffectClass.EXTERNAL_READ,
            output={},
            evidence=[
                _evidence(context=context, action="resolver.action", side_effect_class=SideEffectClass.EXTERNAL_READ)
            ],
            summary="wrong side effect",
        )

    registry.register(
        ActionDefinition(
            name="resolver.action",
            handler=handler,
            provider="test",
            side_effect_class=SideEffectClass.EXTERNAL_READ,
            side_effect_resolver=lambda invocation: SideEffectClass.EXTERNAL_WRITE,
        )
    )

    with pytest.raises(ValueError, match="side_effect_class"):
        registry.invoke(ToolInvocation(action="resolver.action", input={}), _context())


def test_action_registry_revalidates_mutated_action_result_instances() -> None:
    registry = ActionRegistry()

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        result = ActionResult(
            action="custom.action",
            provider="test",
            output={},
            evidence=[_evidence(context=context)],
            summary="valid before mutation",
            confidence=1.0,
        )
        result.confidence = 2.0
        return result

    registry.register(ActionDefinition(name="custom.action", handler=handler, provider="test"))

    with pytest.raises(ValueError, match="valid ActionResult"):
        registry.invoke(ToolInvocation(action="custom.action", input={}), _context())


def test_action_registry_revalidates_model_constructed_action_results() -> None:
    registry = ActionRegistry()

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        return ActionResult.model_construct(
            action="custom.action",
            provider="test",
            output={},
            evidence=[_evidence(context=context)],
            summary="",
        )

    registry.register(ActionDefinition(name="custom.action", handler=handler, provider="test"))

    with pytest.raises(ValueError, match="valid ActionResult"):
        registry.invoke(ToolInvocation(action="custom.action", input={}), _context())


def test_default_registry_keeps_http_read_write_and_webhook_send_authority_separate() -> None:
    registry = get_default_action_registry(rebuild=True)

    assert (
        registry.get("http.request").side_effect_for(
            ToolInvocation(action="http.request", input={"method": "GET", "url": "https://example.com/status"})
        )
        == SideEffectClass.EXTERNAL_READ
    )
    assert (
        registry.get("http.request").side_effect_for(
            ToolInvocation(action="http.request", input={"method": "HEAD", "url": "https://example.com/status"})
        )
        == SideEffectClass.EXTERNAL_READ
    )
    assert (
        registry.get("http.request").side_effect_for(
            ToolInvocation(action="http.request", input={"method": "POST", "url": "https://example.com/hook"})
        )
        == SideEffectClass.EXTERNAL_WRITE
    )
    assert (
        registry.get("webhook.dispatch").side_effect_for(
            ToolInvocation(action="webhook.dispatch", input={"event_type": "task.completed"})
        )
        == SideEffectClass.EXTERNAL_SEND
    )


def test_action_registry_redacts_runtime_credential_values_in_neutral_result_fields() -> None:
    registry = ActionRegistry()
    context = _context()
    context.runtime_credentials["credential.action"] = RuntimeCredentialMaterial(
        reference=CredentialReference(credential_id="cred-1", provider="test", credential_type="api_key"),
        secret_value="sk-neutral-runtime-12345",
        injected_headers={"Authorization": "Bearer sk-neutral-runtime-12345"},
    )

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        return ActionResult(
            action="credential.action",
            provider="test",
            output={
                "message": "handler returned sk-neutral-runtime-12345 in a neutral message",
                "header_echo": "Bearer sk-neutral-runtime-12345",
                "key-sk-neutral-runtime-12345": "credential appears in key",
            },
            evidence=[
                EvidenceItem(
                    evidence_type="action_result",
                    evidence_source="tool.invoke.credential.action",
                    action_name="credential.action",
                    tool_provider="test",
                    tenant_id=context.tenant_id,
                    task_id=str(context.task_id),
                    mission_id=str(context.mission_id) if context.mission_id else None,
                    summary="evidence includes sk-neutral-runtime-12345 in neutral text",
                    structured_payload={
                        "message": "payload sk-neutral-runtime-12345",
                        "key-sk-neutral-runtime-12345": "value",
                    },
                )
            ],
            summary="summary includes sk-neutral-runtime-12345 in neutral text",
            limitations=["limitation includes sk-neutral-runtime-12345 in neutral text"],
        )

    registry.register(ActionDefinition(name="credential.action", handler=handler, provider="test"))

    result = registry.invoke(ToolInvocation(action="credential.action", input={}), context)
    dumped = result.model_dump(mode="json")

    assert "sk-neutral-runtime-12345" not in str(dumped)
    assert "Bearer sk-neutral-runtime-12345" not in str(dumped)
    assert result.summary == "summary includes ***REDACTED*** in neutral text"
    assert result.limitations == ["limitation includes ***REDACTED*** in neutral text"]
    assert result.output == {
        "message": "handler returned ***REDACTED*** in a neutral message",
        "header_echo": "***REDACTED***",
        "key-***REDACTED***": "credential appears in key",
    }
    assert result.evidence[0].summary == "evidence includes ***REDACTED*** in neutral text"
    assert result.evidence[0].structured_payload == {"message": "payload ***REDACTED***", "key-***REDACTED***": "value"}


def test_action_registry_redacts_secret_material_from_results_and_evidence() -> None:
    registry = ActionRegistry()

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        return ActionResult(
            action="redact.action",
            provider="test",
            output={"token": "raw-token", "nested": [{"client_secret": "raw-client-secret"}]},
            evidence=[
                EvidenceItem(
                    evidence_type="action_result",
                    evidence_source="tool.invoke.redact.action",
                    action_name="redact.action",
                    tool_provider="test",
                    tenant_id=context.tenant_id,
                    task_id=str(context.task_id),
                    mission_id=str(context.mission_id) if context.mission_id else None,
                    summary="redaction checked",
                    structured_payload={"api_key": "raw-api-key"},
                )
            ],
            summary="redaction checked",
        )

    registry.register(ActionDefinition(name="redact.action", handler=handler, provider="test"))
    result = registry.invoke(ToolInvocation(action="redact.action", input={}), _context())

    dumped = result.model_dump(mode="json")
    assert "raw-token" not in str(dumped)
    assert "raw-client-secret" not in str(dumped)
    assert "raw-api-key" not in str(dumped)
    assert result.output["token"] == "***REDACTED***"
    assert result.evidence[0].structured_payload["api_key"] == "***REDACTED***"
