from __future__ import annotations

import uuid

import pytest

from backend.services.security.redaction import REDACTED_VALUE
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


def _context_with_runtime_secret(*, action: str, secret: str) -> ActionRuntimeContext:
    context = _context()
    context.runtime_credentials[action] = RuntimeCredentialMaterial(
        reference=CredentialReference(
            credential_id="credential-test",
            provider="test",
            credential_type="api_key",
        ),
        secret_value=secret,
    )
    return context


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


def test_action_registry_redacts_runtime_credential_values_from_neutral_result_fields() -> None:
    registry = ActionRegistry()
    action_name = "neutral.redact"
    runtime_secret = "runtime-secret-value-123"

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
        return ActionResult(
            action=action_name,
            provider="test",
            output={
                "message": f"provider returned {runtime_secret}",
                "nested": [{"value": runtime_secret}],
            },
            evidence=[
                EvidenceItem(
                    evidence_type="action_result",
                    evidence_source=f"tool.invoke.{action_name}",
                    action_name=action_name,
                    tool_provider="test",
                    tenant_id=context.tenant_id,
                    task_id=str(context.task_id),
                    mission_id=str(context.mission_id) if context.mission_id else None,
                    summary=f"evidence saw {runtime_secret}",
                    structured_payload={
                        "message": f"payload {runtime_secret}",
                        "nested": [{"value": runtime_secret}],
                    },
                    provenance={"details": [f"provenance {runtime_secret}"]},
                    side_effect_class=SideEffectClass.NONE,
                )
            ],
            summary=f"summary {runtime_secret}",
            limitations=[f"limitation {runtime_secret}"],
        )

    registry.register(ActionDefinition(name=action_name, handler=handler, provider="test"))
    result = registry.invoke(
        ToolInvocation(action=action_name, input={}),
        _context_with_runtime_secret(action=action_name, secret=runtime_secret),
    )

    dumped = result.model_dump(mode="json")
    assert runtime_secret not in str(dumped)
    assert result.summary == f"summary {REDACTED_VALUE}"
    assert result.limitations == [f"limitation {REDACTED_VALUE}"]
    assert result.output["message"] == f"provider returned {REDACTED_VALUE}"
    assert result.output["nested"] == [{"value": REDACTED_VALUE}]
    assert result.evidence[0].summary == f"evidence saw {REDACTED_VALUE}"
    assert result.evidence[0].structured_payload == {
        "message": f"payload {REDACTED_VALUE}",
        "nested": [{"value": REDACTED_VALUE}],
    }
    assert result.evidence[0].provenance == {"details": [f"provenance {REDACTED_VALUE}"]}


def test_action_registry_validation_error_message_does_not_include_runtime_credential_value() -> None:
    registry = ActionRegistry()
    action_name = "invalid.redact"
    runtime_secret = "runtime-secret-value-123"

    def handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> object:
        return {
            "action": action_name,
            "provider": "test",
            "output": {"message": runtime_secret},
            "evidence": [],
            "summary": "",
        }

    registry.register(ActionDefinition(name=action_name, handler=handler, provider="test"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="valid ActionResult") as exc_info:
        registry.invoke(
            ToolInvocation(action=action_name, input={}),
            _context_with_runtime_secret(action=action_name, secret=runtime_secret),
        )

    assert runtime_secret not in str(exc_info.value)
