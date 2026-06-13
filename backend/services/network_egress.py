from __future__ import annotations

import ipaddress
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
BLOCKED_HOST_FRAGMENTS = {"internal", "intranet", "metadata", "169.254.169.254"}
DEFAULT_RESPONSE_TEXT_LIMIT = 4096

IPAddress = IPv4Address | IPv6Address


class NetworkEgressError(ValueError):
    """Fail-closed network egress authority error with evidence-safe text."""


@dataclass(frozen=True)
class VettedNetworkDestination:
    """A destination whose hostname and DNS answers have been fail-closed vetted."""

    original_url: str
    connect_url: str
    pinned_ip: IPAddress
    sni_hostname: str
    host_header: str


@dataclass(frozen=True)
class NetworkEgressResponse:
    """Bounded response shape returned by network egress authority."""

    status_code: int
    headers: dict[str, str]
    body_text: str
    body_truncated: bool


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


def _safe_error(action_name: str, detail: str) -> NetworkEgressError:
    return NetworkEgressError(f"{action_name} {detail}")


class NetworkEgressAuthority:
    """Shared outbound HTTP authority for runtime-authorized tool actions.

    This service is intentionally not a runtime engine: it does not claim,
    start, complete, fail, authorize, or dispatch tasks. Callers must already be
    inside a runtime-authorized action path before they ask this service to vet
    and perform outbound network I/O.
    """

    def vet_https_url(
        self,
        url: str,
        *,
        allowed_hosts: list[str] | None = None,
        action_name: str = "network egress",
    ) -> VettedNetworkDestination:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise _safe_error(action_name, "only allows https URLs")
        host = (parsed.hostname or "").strip().lower().rstrip(".")
        if not host:
            raise _safe_error(action_name, "URL must include a hostname")
        normalized_allowed_hosts = [item.lower().strip().rstrip(".") for item in (allowed_hosts or []) if item.strip()]
        if normalized_allowed_hosts and host not in normalized_allowed_hosts:
            raise _safe_error(action_name, "host is not in allowed_hosts")
        if host in BLOCKED_HOSTNAMES or host.endswith(".local") or ".local." in host:
            raise _safe_error(action_name, "blocked local hostname")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if any(fragment in host for fragment in BLOCKED_HOST_FRAGMENTS):
                raise _safe_error(action_name, "blocked internal hostname") from None
            try:
                infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
            except socket.gaierror as exc:
                raise _safe_error(action_name, "DNS resolution failed") from exc
            resolved_addresses: list[IPAddress] = []
            seen: set[IPAddress] = set()
            for info in infos:
                resolved = ipaddress.ip_address(info[4][0])
                if resolved in seen:
                    continue
                seen.add(resolved)
                resolved_addresses.append(resolved)
                if _is_blocked_ip(resolved) or not resolved.is_global:
                    raise _safe_error(action_name, "blocked private DNS resolution") from None
            if not resolved_addresses:
                raise _safe_error(action_name, "DNS resolution did not return a public routable address") from None
            pinned_ip = resolved_addresses[0]
        else:
            if _is_blocked_ip(ip) or not ip.is_global:
                raise _safe_error(action_name, "blocked private IP literal")
            pinned_ip = ip
        return VettedNetworkDestination(
            original_url=url,
            connect_url=_connect_url_for_pinned_ip(url, pinned_ip=pinned_ip),
            pinned_ip=pinned_ip,
            sni_hostname=host,
            host_header=_host_header_value(host, parsed.port),
        )

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
        timeout_seconds: float = 10.0,
        allowed_hosts: list[str] | None = None,
        action_name: str = "network egress",
        response_text_limit: int = DEFAULT_RESPONSE_TEXT_LIMIT,
        client: Any | None = None,
    ) -> tuple[VettedNetworkDestination, NetworkEgressResponse]:
        destination = self.vet_https_url(url, allowed_hosts=allowed_hosts, action_name=action_name)
        request_headers = {
            key: value for key, value in (headers or {}).items() if key.lower() not in {"host", "connection"}
        }
        request_headers["Host"] = destination.host_header
        # The connection origin is the pinned IP address, not the original hostname.
        # Force per-request connection close so a supplied long-lived client cannot
        # reuse a TLS connection opened with another hostname's SNI/certificate
        # simply because two vetted hosts resolve to the same public IP.
        request_headers["Connection"] = "close"
        request_kwargs: dict[str, Any] = {
            "headers": request_headers,
            "timeout": timeout_seconds,
            "follow_redirects": False,
            "extensions": {"sni_hostname": destination.sni_hostname},
        }
        if content is not None:
            request_kwargs["content"] = content
        else:
            request_kwargs["json"] = json_body
        try:
            if client is not None:
                response = client.request(method, destination.connect_url, **request_kwargs)
            else:
                with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as http_client:
                    response = http_client.request(method, destination.connect_url, **request_kwargs)
        except httpx.TimeoutException as exc:
            raise _safe_error(action_name, f"network request timed out after {timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise _safe_error(action_name, "network request failed") from exc
        except Exception as exc:
            raise _safe_error(action_name, "network request failed") from exc
        response_text = response.text
        return destination, NetworkEgressResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            body_text=response_text[:response_text_limit],
            body_truncated=len(response_text) > response_text_limit,
        )


_DEFAULT_NETWORK_EGRESS_AUTHORITY = NetworkEgressAuthority()


def get_default_network_egress_authority() -> NetworkEgressAuthority:
    return _DEFAULT_NETWORK_EGRESS_AUTHORITY
