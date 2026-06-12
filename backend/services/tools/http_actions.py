from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from urllib.parse import urlparse, urlunparse

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


IPAddress = IPv4Address | IPv6Address


@dataclass(frozen=True)
class VettedHTTPDestination:
    original_url: str
    connect_url: str
    pinned_ip: IPAddress
    sni_hostname: str
    host_header: str


def _is_blocked_ip(ip: IPAddress) -> bool:
    return bool(
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def _host_header_value(host: str, port: int | None) -> str:
    host_value = f"[{host}]" if ":" in host else host
    if port is not None and port != 443:
        return f"{host_value}:{port}"
    return host_value


def _connect_url_for_pinned_ip(url: str, *, pinned_ip: IPAddress) -> str:
    parsed = urlparse(url)
    ip_host = str(pinned_ip)
    pinned_netloc = f"[{ip_host}]" if pinned_ip.version == 6 else ip_host
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo = f"{userinfo}:{parsed.password}"
        pinned_netloc = f"{userinfo}@{pinned_netloc}"
    if parsed.port is not None:
        pinned_netloc = f"{pinned_netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, pinned_netloc, parsed.path, parsed.params, parsed.query, ""))


def vet_safe_http_destination(url: str, *, allowed_hosts: list[str] | None = None) -> VettedHTTPDestination:
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
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if any(fragment in host for fragment in BLOCKED_HOST_FRAGMENTS):
            raise ValueError("http.request blocked internal hostname") from None
        try:
            infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("http.request DNS resolution failed") from exc
        resolved_addresses: list[IPAddress] = []
        seen: set[IPAddress] = set()
        for info in infos:
            resolved = ipaddress.ip_address(info[4][0])
            if resolved in seen:
                continue
            seen.add(resolved)
            resolved_addresses.append(resolved)
            if _is_blocked_ip(resolved) or not resolved.is_global:
                raise ValueError("http.request blocked private DNS resolution") from None
        public_addresses = resolved_addresses
        if not public_addresses:
            raise ValueError("http.request DNS resolution did not return a public routable address") from None
        pinned_ip = public_addresses[0]
    else:
        if _is_blocked_ip(ip) or not ip.is_global:
            raise ValueError("http.request blocked private IP literal")
        pinned_ip = ip
    return VettedHTTPDestination(
        original_url=url,
        connect_url=_connect_url_for_pinned_ip(url, pinned_ip=pinned_ip),
        pinned_ip=pinned_ip,
        sni_hostname=host,
        host_header=_host_header_value(host, parsed.port),
    )


def validate_safe_http_url(url: str, *, allowed_hosts: list[str] | None = None) -> str:
    return vet_safe_http_destination(url, allowed_hosts=allowed_hosts).original_url


def http_request(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = HttpRequestInput.model_validate(invocation.input)
    destination = vet_safe_http_destination(str(payload.url), allowed_hosts=payload.allowed_hosts)
    url = destination.original_url
    side_effect_class = (
        SideEffectClass.EXTERNAL_WRITE if payload.method in WRITE_METHODS else SideEffectClass.EXTERNAL_READ
    )
    request_headers = {key: value for key, value in payload.headers.items() if key.lower() != "host"}
    request_headers["Host"] = destination.host_header
    with httpx.Client(timeout=payload.timeout_seconds, follow_redirects=False) as client:
        response = client.request(
            payload.method,
            destination.connect_url,
            headers=request_headers,
            json=payload.json_body,
            extensions={"sni_hostname": destination.sni_hostname},
        )
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
