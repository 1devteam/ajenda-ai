from __future__ import annotations

from backend.services.network_egress import (
    VettedNetworkDestination,
    get_default_network_egress_authority,
)
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    HttpRequestInput,
    SideEffectClass,
    ToolInvocation,
)

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def vet_safe_http_destination(url: str, *, allowed_hosts: list[str] | None = None) -> VettedNetworkDestination:
    return get_default_network_egress_authority().vet_https_url(
        url, allowed_hosts=allowed_hosts, action_name="http.request"
    )


def validate_safe_http_url(url: str, *, allowed_hosts: list[str] | None = None) -> str:
    return vet_safe_http_destination(url, allowed_hosts=allowed_hosts).original_url


def http_request(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = HttpRequestInput.model_validate(invocation.input)
    side_effect_class = (
        SideEffectClass.EXTERNAL_WRITE if payload.method in WRITE_METHODS else SideEffectClass.EXTERNAL_READ
    )
    _destination, response = get_default_network_egress_authority().request(
        method=payload.method,
        url=str(payload.url),
        headers=payload.headers,
        json_body=payload.json_body,
        timeout_seconds=payload.timeout_seconds,
        allowed_hosts=payload.allowed_hosts,
        action_name="http.request",
    )
    url = str(payload.url)
    output = {
        "method": payload.method,
        "url": url,
        "status_code": response.status_code,
        "headers": response.headers,
        "body_text": response.body_text,
        "body_truncated": response.body_truncated,
    }
    summary = f"HTTP {payload.method} {url} returned {response.status_code}."
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.http.request",
        action_name="http.request",
        tool_provider="httpx",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload={
            "status_code": response.status_code,
            "url": url,
            "access_mode": "http_request",
            "method": payload.method,
        },
        confidence=1.0,
        limitations=[
            "response body truncated to 4096 characters",
            "redirects disabled",
            "open_write / browser_session modes are reserved expansion doors",
        ],
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> ToolRuntimeAuthority -> ActionRegistry",
            "network_egress_authority": "backend.services.network_egress.NetworkEgressAuthority",
            "library": "httpx",
            "access_mode": "http_request",
            "internet_access": "backend.services.internet",
        },
        side_effect_class=side_effect_class,
    )
    return ActionResult(
        action="http.request",
        provider="httpx",
        side_effect_class=side_effect_class,
        output=output,
        evidence=[evidence],
        summary=summary,
        confidence=1.0,
    )


def http_request_side_effect(invocation: ToolInvocation) -> SideEffectClass:
    payload = HttpRequestInput.model_validate(invocation.input)
    return SideEffectClass.EXTERNAL_WRITE if payload.method in WRITE_METHODS else SideEffectClass.EXTERNAL_READ


def register_http_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="http.request",
            handler=http_request,
            provider="httpx",
            input_model=HttpRequestInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
            side_effect_resolver=http_request_side_effect,
        )
    )
