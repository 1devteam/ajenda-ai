from __future__ import annotations

from typing import Any

import httpx

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import ActionExecutionContext, ActionResult, EvidenceItem, HttpRequestInput

_RESPONSE_BODY_LIMIT = 4096


def http_request(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    parsed = HttpRequestInput.model_validate(payload)
    side_effect_class = "external_read" if parsed.method in {"GET", "HEAD"} else "external_write"
    client = context.http_client or httpx.Client(timeout=parsed.timeout_seconds)
    close_client = context.http_client is None
    try:
        response = client.request(
            parsed.method,
            parsed.url,
            headers=parsed.headers,
            params=parsed.params,
            json=parsed.json_body,
            timeout=parsed.timeout_seconds,
        )
    finally:
        if close_client:
            client.close()
    output = {
        "method": parsed.method,
        "url": parsed.url,
        "http_status": response.status_code,
        "response_body": response.text[:_RESPONSE_BODY_LIMIT],
        "response_headers": dict(response.headers),
    }
    return ActionResult(
        action="http.request",
        side_effect_class=side_effect_class,
        output=output,
        evidence=[
            EvidenceItem(
                evidence_type="action_result",
                evidence_source="tool.invoke.http.request",
                summary=f"HTTP {parsed.method} completed with status {response.status_code}.",
                structured_payload={"http_status": response.status_code, "url": parsed.url},
                confidence=1.0,
                trust_signal={"provider": "httpx"},
            )
        ],
    )


def register_http_actions(registry: ActionRegistry) -> None:
    # Register as external_read by default. The action result can be external_write
    # for non-read methods, so callers that need strict write gating should validate
    # the payload method before invocation.
    registry.register(
        ActionDefinition(
            name="http.request",
            handler=http_request,
            side_effect_class="external_read",
            allowed_result_side_effect_classes=("external_read", "external_write"),
        )
    )
