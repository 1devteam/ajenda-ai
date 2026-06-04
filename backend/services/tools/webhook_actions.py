from __future__ import annotations

import uuid
from typing import Any

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import ActionExecutionContext, ActionResult, EvidenceItem, WebhookDispatchInput
from backend.services.webhook_dispatch import WebhookDispatchService


def webhook_dispatch(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    parsed = WebhookDispatchInput.model_validate(payload)
    try:
        tenant_uuid = uuid.UUID(context.tenant_id)
    except ValueError as exc:
        raise ValueError("webhook.dispatch requires UUID tenant_id") from exc
    session = context.session_factory()
    try:
        service = WebhookDispatchService(session)
        results = service.dispatch_event(
            tenant_id=tenant_uuid,
            event_type=parsed.event_type,
            payload=parsed.payload,
            event_id=parsed.event_id,
            attempt_number=parsed.attempt_number,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    serialized = [
        {
            "delivery_id": str(result.delivery_id),
            "succeeded": result.succeeded,
            "http_status": result.http_status,
            "error": result.error,
        }
        for result in results
    ]
    output = {"event_type": parsed.event_type, "delivery_count": len(results), "deliveries": serialized}
    return ActionResult(
        action="webhook.dispatch",
        side_effect_class="external_send",
        output=output,
        evidence=[
            EvidenceItem(
                evidence_type="action_result",
                evidence_source="tool.invoke.webhook.dispatch",
                summary=f"Dispatched webhook event to {len(results)} endpoint(s).",
                structured_payload=output,
                confidence=1.0,
                trust_signal={"provider": "WebhookDispatchService"},
            )
        ],
    )


def register_webhook_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(name="webhook.dispatch", handler=webhook_dispatch, side_effect_class="external_send")
    )
