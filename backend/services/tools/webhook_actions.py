from __future__ import annotations

import uuid

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
    WebhookDispatchInput,
)
from backend.services.webhook_dispatch import WebhookDispatchService


def webhook_dispatch(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = WebhookDispatchInput.model_validate(invocation.input)
    event_id = payload.event_id or _derive_stable_event_id(invocation=invocation, context=context)
    if context.session_factory is None:
        raise ValueError("webhook.dispatch requires a session_factory")
    session = context.session_factory()
    try:
        service = WebhookDispatchService(session)
        results = service.dispatch_event(
            tenant_id=uuid.UUID(context.tenant_id),
            event_type=payload.event_type,
            payload=payload.payload,
            event_id=event_id,
            attempt_number=payload.attempt_number,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    deliveries = [
        {
            "delivery_id": str(result.delivery_id),
            "succeeded": result.succeeded,
            "http_status": result.http_status,
            "error": result.error,
        }
        for result in results
    ]
    output = {
        "event_type": payload.event_type,
        "event_id": str(event_id),
        "delivery_count": len(deliveries),
        "deliveries": deliveries,
    }
    summary = f"Dispatched webhook event {payload.event_type} to {len(deliveries)} endpoint(s)."
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.webhook.dispatch",
        action_name="webhook.dispatch",
        tool_provider="WebhookDispatchService",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=output,
        confidence=1.0,
        limitations=["single dispatch attempt; retry scheduling remains caller/runtime responsibility"],
        provenance={
            "service": "backend.services.webhook_dispatch.WebhookDispatchService",
            "network_egress_authority": "backend.services.network_egress.NetworkEgressAuthority",
        },
        side_effect_class=SideEffectClass.EXTERNAL_SEND,
    )
    return ActionResult(
        action="webhook.dispatch",
        provider="WebhookDispatchService",
        side_effect_class=SideEffectClass.EXTERNAL_SEND,
        output=output,
        evidence=[evidence],
        summary=summary,
        confidence=1.0,
    )


def _derive_stable_event_id(*, invocation: ToolInvocation, context: ActionRuntimeContext) -> uuid.UUID:
    if invocation.idempotency_key:
        return uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"ajenda:webhook:{context.tenant_id}:{invocation.idempotency_key}",
        )
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"ajenda:webhook:{context.tenant_id}:{context.task_id}",
    )


def register_webhook_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="webhook.dispatch",
            handler=webhook_dispatch,
            provider="WebhookDispatchService",
            input_model=WebhookDispatchInput,
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
        )
    )
