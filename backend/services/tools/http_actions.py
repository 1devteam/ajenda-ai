from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    HttpRequestInput,
    SideEffectClass,
    ToolInvocation,
)

BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
BLOCKED_HOST_FRAGMENTS = {"internal", "intranet", "metadata", "169.254.169.254"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def validate_safe_http_url(url: str, *, allowed_hosts: list[str] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("http.request only allows https URLs")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("http.request URL must include a hostname")
    allowed_hosts = [item.lower().strip().rstrip(".") for item in (allowed_hosts or []) if item.strip()]
    if allowed_hosts and host not in allowed_hosts:
        raise ValueError("http.request host is not in allowed_hosts")
    if host in BLOCKED_HOSTNAMES or host.endswith(".local") or ".local." in host:
        raise ValueError("http.request blocked local hostname")
    if any(fragment in host for fragment in BLOCKED_HOST_FRAGMENTS):
        raise ValueError("http.request blocked internal hostname")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            infos = []
        for info in infos:
            resolved = ipaddress.ip_address(info[4][0])
            if _is_blocked_ip(resolved):
                raise ValueError("http.request blocked private DNS resolution") from None
    else:
        if _is_blocked_ip(ip):
            raise ValueError("http.request blocked private IP literal")
    return url


def http_request(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = HttpRequestInput.model_validate(invocation.input)
    url = validate_safe_http_url(str(payload.url), allowed_hosts=payload.allowed_hosts)
    side_effect_class = (
        SideEffectClass.EXTERNAL_WRITE if payload.method in WRITE_METHODS else SideEffectClass.EXTERNAL_READ
    )
    with httpx.Client(timeout=payload.timeout_seconds, follow_redirects=False) as client:
        response = client.request(payload.method, url, headers=payload.headers, json=payload.json_body)
    text = response.text[:4096]
    output = {
        "method": payload.method,
        "url": url,
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "body_text": text,
        "body_truncated": len(response.text) > 4096,
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
        structured_payload={"status_code": response.status_code, "url": url},
        confidence=1.0,
        limitations=["response body truncated to 4096 characters", "redirects disabled"],
        provenance={"runtime_path": "TaskDispatcher -> tool.invoke -> ActionRegistry", "library": "httpx"},
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
