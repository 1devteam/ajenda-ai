from __future__ import annotations

import pytest

from backend.services.credentials.runtime_authority import (
    CredentialRecord,
    CredentialRuntimeAuthority,
    InMemoryCredentialRuntimeRepository,
)
from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.provider_read_actions import ProviderExternalReadInput
from backend.services.tools.runtime_authority import ToolRuntimeAuthority, ToolRuntimeAuthorityError
from backend.services.tools.schemas import SideEffectClass
from tests.unit.tools.test_tool_runtime_authority import _context, _task


class _EgressSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def request(self, **kwargs: object) -> tuple[VettedNetworkDestination, NetworkEgressResponse]:
        self.calls.append(kwargs)
        assert kwargs["method"] in {"GET", "HEAD"}
        assert kwargs["action_name"] == "provider.external_read"
        assert kwargs["json_body"] is None
        assert kwargs["allowed_hosts"] == ["example.com"]
        headers = kwargs["headers"]
        assert isinstance(headers, dict)
        assert headers["Authorization"] == "Bearer sk-provider-secret"
        return (
            VettedNetworkDestination(
                original_url=str(kwargs["url"]),
                connect_url="https://93.184.216.34/resource",
                pinned_ip=__import__("ipaddress").ip_address("93.184.216.34"),
                sni_hostname="example.com",
                host_header="example.com",
            ),
            NetworkEgressResponse(
                status_code=200,
                headers={"x-token-echo": "sk-provider-secret"},
                body_text="provider body sk-provider-secret",
                body_truncated=False,
            ),
        )


def _credential_authority(record: CredentialRecord | None = None) -> CredentialRuntimeAuthority:
    return CredentialRuntimeAuthority(repository=InMemoryCredentialRuntimeRepository([record] if record else []))


def _record(**overrides: object) -> CredentialRecord:
    values = {
        "credential_id": "cred-1",
        "tenant_id": "tenant",
        "provider": "external_read_provider",
        "credential_type": "api_key",
        "allowed_actions": ("provider.external_read",),
        "allowed_side_effect_classes": (SideEffectClass.EXTERNAL_READ,),
        "trusted_destination_hosts": ("example.com",),
        "secret_value": "sk-provider-secret",
    }
    values.update(overrides)
    return CredentialRecord.model_validate(values)


def _reference(**overrides: object) -> dict[str, object]:
    values = {
        "schema_version": 1,
        "credential_id": "cred-1",
        "provider": "external_read_provider",
        "credential_type": "api_key",
    }
    values.update(overrides)
    return values


def test_provider_external_read_rejects_write_methods_and_raw_secret_input() -> None:
    with pytest.raises(ValueError, match="GET or HEAD"):
        ProviderExternalReadInput.model_validate({"method": "POST", "url": "https://example.com/resource"})
    with pytest.raises(ValueError, match="raw credential"):
        ProviderExternalReadInput.model_validate(
            {"method": "GET", "url": "https://example.com/resource", "headers": {"Authorization": "Bearer raw"}}
        )


def test_provider_external_read_uses_egress_and_redacts_runtime_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.tools import provider_read_actions, runtime_authority

    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", lambda **kwargs: None)
    spy = _EgressSpy()
    monkeypatch.setattr(provider_read_actions, "get_default_network_egress_authority", lambda: spy)
    authority = ToolRuntimeAuthority(
        registry=get_default_action_registry(rebuild=True),
        credential_authority=_credential_authority(_record()),
    )

    result = authority.execute(
        task=_task(
            action="provider.external_read",
            input_payload={"method": "GET", "url": "https://example.com/resource"},
            metadata={"credential_reference": _reference()},
        ),
        context=_context(),
    )

    assert len(spy.calls) == 1
    assert result["action"] == "provider.external_read"
    assert result["side_effect_class"] == "external_read"
    assert result["output"]["body_text"] == "provider body ***REDACTED***"
    assert result["output"]["headers"] == {"x-token-echo": "***REDACTED***"}
    assert result["evidence"][0]["side_effect_class"] == "external_read"
    assert result["evidence"][0]["provenance"]["network_egress_authority"].endswith("NetworkEgressAuthority")
    assert "sk-provider-secret" not in str(result)
    assert "runtime_credentials" not in result["runtime_context"]


def test_provider_external_read_rejects_untrusted_host_before_egress_and_auth_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.tools import provider_read_actions, runtime_authority

    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", lambda **kwargs: None)
    spy = _EgressSpy()
    monkeypatch.setattr(provider_read_actions, "get_default_network_egress_authority", lambda: spy)
    authority = ToolRuntimeAuthority(
        registry=get_default_action_registry(rebuild=True),
        credential_authority=_credential_authority(_record()),
    )

    with pytest.raises(ValueError, match="not trusted for credential"):
        authority.execute(
            task=_task(
                action="provider.external_read",
                input_payload={
                    "method": "GET",
                    "url": "https://attacker.example.net/resource",
                    "allowed_hosts": ["attacker.example.net"],
                },
                metadata={"credential_reference": _reference()},
            ),
            context=_context(),
        )

    assert spy.calls == []


def test_provider_external_read_invocation_allowed_hosts_cannot_expand_trusted_destinations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.tools import provider_read_actions, runtime_authority

    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", lambda **kwargs: None)
    spy = _EgressSpy()
    monkeypatch.setattr(provider_read_actions, "get_default_network_egress_authority", lambda: spy)
    authority = ToolRuntimeAuthority(
        registry=get_default_action_registry(rebuild=True),
        credential_authority=_credential_authority(_record()),
    )

    result = authority.execute(
        task=_task(
            action="provider.external_read",
            input_payload={
                "method": "GET",
                "url": "https://example.com/resource",
                "allowed_hosts": ["attacker.example.net"],
            },
            metadata={"credential_reference": _reference()},
        ),
        context=_context(),
    )

    assert result["output"]["status_code"] == 200
    assert spy.calls[0]["allowed_hosts"] == ["example.com"]


def test_provider_external_read_private_destination_remains_blocked_by_network_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.tools import runtime_authority

    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", lambda **kwargs: None)
    authority = ToolRuntimeAuthority(
        registry=get_default_action_registry(rebuild=True),
        credential_authority=_credential_authority(_record(trusted_destination_hosts=("localhost",))),
    )

    with pytest.raises(ValueError, match="blocked local hostname"):
        authority.execute(
            task=_task(
                action="provider.external_read",
                input_payload={"method": "GET", "url": "https://localhost/resource"},
                metadata={"credential_reference": _reference()},
            ),
            context=_context(),
        )


def test_provider_external_read_credential_denials(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.tools import runtime_authority

    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", lambda **kwargs: None)
    cases = [
        (_credential_authority(), _reference(), "not visible"),
        (_credential_authority(_record(tenant_id="other")), _reference(), "not visible"),
        (_credential_authority(_record(enabled=False)), _reference(), "disabled"),
        (_credential_authority(_record(provider="other")), _reference(), "stored credential"),
        (_credential_authority(_record(credential_type="oauth_token")), _reference(), "stored credential"),
        (_credential_authority(_record()), _reference(provider="wrong"), "provider/type"),
        (_credential_authority(_record()), None, "credential_reference is required"),
    ]
    for credential_authority, reference, message in cases:
        metadata = {"credential_reference": reference} if reference is not None else {}
        authority = ToolRuntimeAuthority(
            registry=get_default_action_registry(rebuild=True), credential_authority=credential_authority
        )
        with pytest.raises(ToolRuntimeAuthorityError, match=message):
            authority.execute(
                task=_task(
                    action="provider.external_read",
                    input_payload={"method": "GET", "url": "https://example.com/resource"},
                    metadata=metadata,
                ),
                context=_context(),
            )


def test_provider_external_read_tenant_mismatch_fails_closed() -> None:
    authority = ToolRuntimeAuthority(registry=get_default_action_registry(rebuild=True))
    with pytest.raises(ToolRuntimeAuthorityError, match="tenant mismatch"):
        authority.authorize(
            task=_task(action="provider.external_read", input_payload={"url": "https://example.com"}),
            context=_context(tenant_id="other"),
        )
