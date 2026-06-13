from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.domain.execution_task import ExecutionTask
from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.services.webhook_secret_protector import WebhookSecretProtector
from backend.workers.handlers.tool_invoke import tool_invoke_handler


class SessionStub:
    def close(self) -> None:
        return None


def _session_factory() -> SessionStub:
    return SessionStub()


def _task(*, tenant_id: str, metadata: dict[str, Any]) -> ExecutionTask:
    return ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="tool task",
        description="tool task",
        status="running",
        metadata_json={"task_type": "tool.invoke", **metadata},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )


def _context(tenant_id: str) -> dict[str, Any]:
    return {
        "worker_id": "worker",
        "tenant_id": tenant_id,
        "lease_id": str(uuid.uuid4()),
        "session_factory": _session_factory,
    }


def test_tool_invoke_handler_success_returns_dispatcher_valid_evidence_output() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(
        tenant_id=tenant_id,
        metadata={"tool_invocation": {"action": "record.search", "input": {"record_type": "account", "query": "Acme"}}},
    )

    result = tool_invoke_handler(task, _context(tenant_id))

    assert result["handler"] == "tool.invoke"
    assert result["status"] == "completed"
    assert result["action"] == "record.search"
    assert result["output"]["count"] == 1
    assert result["evidence"][0]["tenant_id"] == tenant_id
    assert result["runtime_context"]["task_id"] == str(task.id)


def test_tool_invoke_handler_rejects_tenant_mismatch() -> None:
    task = _task(
        tenant_id=str(uuid.uuid4()),
        metadata={"tool_invocation": {"action": "record.search", "input": {"record_type": "account"}}},
    )

    with pytest.raises(ValueError, match="tenant mismatch"):
        tool_invoke_handler(task, _context(str(uuid.uuid4())))


@pytest.mark.parametrize(
    "metadata,match",
    [
        ({}, "tool_invocation"),
        ({"tool_invocation": {"input": {}}}, "invalid tool_invocation"),
        ({"tool_invocation": {"action": "missing.action", "input": {}}}, "unknown action"),
    ],
)
def test_tool_invoke_handler_rejects_invalid_invocations(metadata: dict[str, Any], match: str) -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, metadata=metadata)

    with pytest.raises(ValueError, match=match):
        tool_invoke_handler(task, _context(tenant_id))


def test_tool_invoke_handler_fails_side_effecting_action_without_authority() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(
        tenant_id=tenant_id,
        metadata={
            "tool_invocation": {
                "action": "record.write",
                "input": {"record_type": "contact", "data": {"name": "Avery"}},
            }
        },
    )

    with pytest.raises(ValueError, match="runtime promotion requires explicit capability/adapter authority"):
        tool_invoke_handler(task, _context(tenant_id))


def test_tool_invoke_handler_rejects_side_effect_authorization_without_capability_or_adapter() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(
        tenant_id=tenant_id,
        metadata={
            "tool_invocation": {
                "action": "record.write",
                "input": {"record_type": "contact", "data": {"name": "Avery"}},
            },
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["record.write"],
                    "reason": "unit test authorization",
                    "approved_by": "qa",
                }
            },
        },
    )

    with pytest.raises(ValueError, match="runtime promotion requires explicit capability/adapter authority"):
        tool_invoke_handler(task, _context(tenant_id))


def test_tool_invoke_handler_gates_http_write_methods_before_network_call() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(
        tenant_id=tenant_id,
        metadata={
            "tool_invocation": {
                "action": "http.request",
                "input": {"method": "POST", "url": "https://example.com/hook", "json_body": {"ok": True}},
            }
        },
    )

    with pytest.raises(ValueError, match="runtime promotion requires explicit capability/adapter authority"):
        tool_invoke_handler(task, _context(tenant_id))


class _ProviderEgressSpy:
    def __init__(self, *, expected_secret: str) -> None:
        self.expected_secret = expected_secret
        self.calls: list[dict[str, object]] = []

    def request(self, **kwargs: object) -> tuple[VettedNetworkDestination, NetworkEgressResponse]:
        self.calls.append(kwargs)
        headers = kwargs["headers"]
        assert isinstance(headers, dict)
        assert headers["Authorization"] == f"Bearer {self.expected_secret}"
        assert kwargs["allowed_hosts"] == ["example.com"]
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
                headers={"x-secret-echo": self.expected_secret},
                body_text=f"provider body {self.expected_secret}",
                body_truncated=False,
            ),
        )


def test_tool_invoke_handler_uses_live_sqlalchemy_credential_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.services.tools import provider_read_actions, runtime_authority

    monkeypatch.setattr(runtime_authority, "validate_capability_action_authority", lambda **kwargs: None)
    plaintext_secret, ciphertext_secret = WebhookSecretProtector().generate_secret()
    spy = _ProviderEgressSpy(expected_secret=plaintext_secret)
    monkeypatch.setattr(provider_read_actions, "get_default_network_egress_authority", lambda: spy)

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    ProviderRuntimeCredential.__table__.create(engine)
    local_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    tenant_id = str(uuid.uuid4())
    with local_session_factory() as session:
        session.add(
            ProviderRuntimeCredential(
                id="runtime-cred-1",
                tenant_id=tenant_id,
                credential_id="cred-1",
                provider="external_read_provider",
                credential_type="api_key",
                allowed_actions=["provider.external_read"],
                allowed_side_effect_classes=["external_read"],
                trusted_destination_hosts=["example.com"],
                secret_ciphertext=ciphertext_secret,
            )
        )
        session.commit()

    task = _task(
        tenant_id=tenant_id,
        metadata={
            "tool_invocation": {
                "action": "provider.external_read",
                "input": {"method": "GET", "url": "https://example.com/resource"},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "cred-1",
                "provider": "external_read_provider",
                "credential_type": "api_key",
            },
        },
    )

    result = tool_invoke_handler(
        task,
        {
            "worker_id": "worker",
            "tenant_id": tenant_id,
            "lease_id": str(uuid.uuid4()),
            "session_factory": local_session_factory,
        },
    )

    assert len(spy.calls) == 1
    assert result["action"] == "provider.external_read"
    assert result["output"]["body_text"] == "provider body ***REDACTED***"
    assert result["output"]["headers"] == {"x-secret-echo": "***REDACTED***"}
    assert plaintext_secret not in str(result)
    assert "runtime_credentials" not in result["runtime_context"]
