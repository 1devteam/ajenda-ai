from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from backend.services.credentials.runtime_authority import CredentialRequirement
from backend.services.network_egress import get_default_network_egress_authority
from backend.services.security.redaction import contains_sensitive_key
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
)

PROVIDER_EXTERNAL_READ_ACTION = "provider.external_read"
PROVIDER_EXTERNAL_READ_PROVIDER = "external_read_provider"
PROVIDER_EXTERNAL_READ_CREDENTIAL_TYPE = "api_key"
SAFE_PROVIDER_EXTERNAL_READ_HEADERS = frozenset(
    {
        "accept",
        "accept-language",
        "cache-control",
        "if-modified-since",
        "if-none-match",
        "user-agent",
    }
)
CREDENTIAL_LIKE_HEADER_VALUE_FRAGMENTS = (
    "bearer ",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token=",
    "session=",
    "secret",
    "password",
    "private_key",
    "client_secret",
)


def _normalize_safe_provider_header_name(name: str) -> str:
    return name.strip().lower()


def _header_value_contains_credential_material(value: str) -> bool:
    normalized = value.lower()
    return any(fragment in normalized for fragment in CREDENTIAL_LIKE_HEADER_VALUE_FRAGMENTS)


class ProviderExternalReadInput(BaseModel):
    """Narrow provider read input for HTTPS GET/HEAD only."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(default="GET", max_length=4)
    url: HttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=5.0, ge=0.1, le=10.0)
    allowed_hosts: list[str] = Field(default_factory=list)

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        normalized = value.upper().strip()
        if normalized not in {"GET", "HEAD"}:
            raise ValueError("provider.external_read only supports GET or HEAD")
        return normalized

    @field_validator("headers")
    @classmethod
    def validate_safe_headers(cls, value: dict[str, str]) -> dict[str, str]:
        if contains_sensitive_key(value):
            raise ValueError("provider.external_read headers must not include raw credential material")
        normalized_headers: dict[str, str] = {}
        for raw_name, raw_value in value.items():
            header_name = raw_name.strip()
            normalized_name = _normalize_safe_provider_header_name(header_name)
            if normalized_name not in SAFE_PROVIDER_EXTERNAL_READ_HEADERS:
                raise ValueError("provider.external_read headers must use the safe read-only header allowlist")
            header_value = str(raw_value)
            if _header_value_contains_credential_material(header_value):
                raise ValueError("provider.external_read headers must not include credential-like values")
            if normalized_name in normalized_headers:
                raise ValueError("provider.external_read headers must not contain duplicate header names")
            normalized_headers[normalized_name] = header_value
        return normalized_headers


def _normalized_url_host(url: str) -> str:
    return (urlparse(url).hostname or "").strip().lower().rstrip(".")


def _trusted_destination_hosts(credential_hosts: tuple[str, ...]) -> list[str]:
    return [host.strip().lower().rstrip(".") for host in credential_hosts if host.strip()]


def _validate_trusted_credential_destination(*, url: str, trusted_hosts: tuple[str, ...]) -> list[str]:
    normalized_trusted_hosts = _trusted_destination_hosts(trusted_hosts)
    if not normalized_trusted_hosts:
        raise ValueError("provider.external_read credential has no trusted destination hosts")
    host = _normalized_url_host(url)
    if host not in normalized_trusted_hosts:
        raise ValueError("provider.external_read URL host is not trusted for credential")
    return normalized_trusted_hosts


def provider_external_read(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = ProviderExternalReadInput.model_validate(invocation.input)
    credential = context.runtime_credentials.get(PROVIDER_EXTERNAL_READ_ACTION)
    if credential is None:
        raise ValueError("provider.external_read requires runtime credential material")

    trusted_hosts = _validate_trusted_credential_destination(
        url=str(payload.url),
        trusted_hosts=credential.trusted_destination_hosts,
    )
    headers = dict(payload.headers)
    headers["Authorization"] = f"Bearer {credential.secret_value}"
    _destination, response = get_default_network_egress_authority().request(
        method=payload.method,
        url=str(payload.url),
        headers=headers,
        json_body=None,
        timeout_seconds=payload.timeout_seconds,
        allowed_hosts=trusted_hosts,
        action_name=PROVIDER_EXTERNAL_READ_ACTION,
    )
    url = str(payload.url)
    output = {
        "method": payload.method,
        "url": url,
        "status_code": response.status_code,
        "headers": response.headers,
        "body_text": response.body_text,
        "body_truncated": response.body_truncated,
        "credential_reference": {
            "credential_id": credential.reference.credential_id,
            "provider": credential.reference.provider,
            "credential_type": credential.reference.credential_type,
        },
    }
    summary = f"Read-only provider {payload.method} {url} returned {response.status_code}."
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.provider.external_read",
        action_name=PROVIDER_EXTERNAL_READ_ACTION,
        tool_provider=PROVIDER_EXTERNAL_READ_PROVIDER,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload={
            "method": payload.method,
            "url": url,
            "status_code": response.status_code,
            "credential_id": credential.reference.credential_id,
        },
        records_inspected=[url],
        confidence=1.0,
        limitations=["read-only GET/HEAD only", "response body truncated to 4096 characters", "redirects disabled"],
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> ToolRuntimeAuthority -> ActionRegistry -> NetworkEgressAuthority",
            "network_egress_authority": "backend.services.network_egress.NetworkEgressAuthority",
            "provider_activation_scope": "read-only external provider foundation; no writes, sends, publishes, OAuth refresh, or SDK fleet",
        },
        side_effect_class=SideEffectClass.EXTERNAL_READ,
    )
    return ActionResult(
        action=PROVIDER_EXTERNAL_READ_ACTION,
        provider=PROVIDER_EXTERNAL_READ_PROVIDER,
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output=output,
        evidence=[evidence],
        records_inspected=[url],
        summary=summary,
        confidence=1.0,
        limitations=["read-only GET/HEAD only", "redirects disabled"],
    )


def register_provider_read_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name=PROVIDER_EXTERNAL_READ_ACTION,
            handler=provider_external_read,
            provider=PROVIDER_EXTERNAL_READ_PROVIDER,
            input_model=ProviderExternalReadInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
            credential_requirement=CredentialRequirement(
                provider=PROVIDER_EXTERNAL_READ_PROVIDER,
                credential_type=PROVIDER_EXTERNAL_READ_CREDENTIAL_TYPE,
                allowed_side_effect_classes=(SideEffectClass.EXTERNAL_READ,),
            ),
        )
    )
