from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.domain.execution_task import ExecutionTask
from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.main import create_app
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector
from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.workers.handlers.tool_invoke import tool_invoke_handler

pytestmark = pytest.mark.integration


def _auth_headers(*, tenant_id: str, api_key: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-Api-Key": api_key}


def _store_hubspot_credential(session: Session, *, tenant_id: str, credential_id: str = "hubspot-crm") -> str:
    protector = RuntimeCredentialSecretProtector()
    ciphertext = protector.encrypt_secret("integration-test-hubspot-pak")
    row = ProviderRuntimeCredential(
        id=f"prc-{uuid.uuid4()}",
        tenant_id=tenant_id,
        credential_id=credential_id,
        provider="external_crm",
        credential_type="api_key",
        enabled=True,
        revoked=False,
        deleted=False,
        allowed_actions=["sales.research", "crm.research", "gtm.crm_upsert"],
        allowed_side_effect_classes=["external_read", "external_write"],
        trusted_destination_hosts=["hubspot-crm-ingress"],
        secret_ciphertext=ciphertext,
    )
    session.add(row)
    session.flush()
    return credential_id


def _egress_spy(*, status_code: int = 200, body: str = '{"results":[],"count":0}') -> MagicMock:
    authority = MagicMock()
    authority.request.return_value = (
        VettedNetworkDestination(
            original_url="https://hubspot-crm-ingress/v1/search",
            connect_url="https://10.0.0.5/v1/search",
            pinned_ip=__import__("ipaddress").ip_address("10.0.0.5"),
            sni_hostname="hubspot-crm-ingress",
            host_header="hubspot-crm-ingress",
        ),
        NetworkEgressResponse(status_code=status_code, headers={}, body_text=body, body_truncated=False),
    )
    return authority


@pytest.fixture
def hubspot_runtime_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_HUBSPOT_CRM_ADAPTER_PUBLIC_HOST", "hubspot-crm-ingress")
    monkeypatch.setenv("AJENDA_NETWORK_EGRESS_ALLOW_PRIVATE_DESTINATIONS", "true")
    monkeypatch.setenv("AJENDA_NETWORK_EGRESS_TLS_VERIFY", "false")
    from backend.app.config import get_settings

    get_settings.cache_clear()


def _provision_operational_tenant(client: TestClient) -> tuple[str, str]:
    email = f"cred-flow-{uuid.uuid4().hex[:8]}@example.com"
    signup = client.post(
        "/v1/onboarding/signup",
        json={"org_name": "Cred Flow Co", "email": email},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert signup.status_code == 201, signup.text
    tenant_id = signup.json()["tenant_id"]
    token = signup.json()["verification_token"]
    verify = client.post(
        "/v1/onboarding/verify-email",
        json={"token": token},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert verify.status_code == 200, verify.text
    bootstrap_key = verify.json()["api_key"]
    promote = client.post(
        "/v1/onboarding/promote-bootstrap-key",
        headers=_auth_headers(tenant_id=tenant_id, api_key=bootstrap_key),
    )
    assert promote.status_code == 200, promote.text
    return tenant_id, promote.json()["api_key"]


def test_provider_credentials_api_register_list_revoke(
    monkeypatch: pytest.MonkeyPatch,
    integration_env: None,
    pg_engine: object,
    hubspot_runtime_settings: None,
) -> None:
    monkeypatch.setenv("AJENDA_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN", "true")
    monkeypatch.setenv("AJENDA_EMAIL_PROVIDER", "noop")
    with TestClient(create_app()) as client:
        tenant_id, api_key = _provision_operational_tenant(client)

        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=_auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "integration": "hubspot",
                "secret_value": "tenant-hubspot-pak",
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        body = create_resp.json()
        assert body["credential"]["credential_id"] == "hubspot-crm"
        assert "tenant-hubspot-pak" not in create_resp.text

        list_resp = client.get(
            "/v1/account/provider-credentials",
            headers=_auth_headers(tenant_id=tenant_id, api_key=api_key),
        )
        assert list_resp.status_code == 200
        assert any(item["credential_id"] == "hubspot-crm" for item in list_resp.json()["credentials"])

        revoke_resp = client.post(
            "/v1/account/provider-credentials/hubspot-crm/revoke",
            headers=_auth_headers(tenant_id=tenant_id, api_key=api_key),
        )
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["revoked"] is True


def test_crm_research_and_upsert_happy_path_via_adapter_contract(
    integration_env: None,
    hubspot_runtime_settings: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    _store_hubspot_credential(pg_session, tenant_id=tenant_id)
    pg_session.commit()

    search_authority = _egress_spy(status_code=200, body='{"results":[{"id":"1"}],"count":1,"source":"hubspot"}')
    upsert_authority = _egress_spy(
        status_code=200,
        body='{"id":"999","created":true,"record_type":"contact","hubspot_object_type":"contacts"}',
    )

    combined_authority = MagicMock()

    def _route_request(**kwargs):
        if str(kwargs.get("method", "GET")).upper() == "POST":
            return upsert_authority.request(**kwargs)
        return search_authority.request(**kwargs)

    combined_authority.request.side_effect = _route_request
    monkeypatch.setattr(
        "backend.services.plugins.crm_client.get_default_network_egress_authority",
        lambda: combined_authority,
    )
    monkeypatch.setattr(
        "backend.services.tools.runtime_authority.validate_capability_action_authority",
        lambda **kwargs: None,
    )

    def _session_factory():
        return pg_session

    context = {
        "worker_id": "worker-test",
        "tenant_id": tenant_id,
        "lease_id": str(uuid.uuid4()),
        "session_factory": _session_factory,
    }

    research_task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="crm research",
        description="crm research",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "crm.research",
                "input": {"lead": {"company": "Acme", "domain": "acme.com"}},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "credential_type": "api_key",
            },
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    research_result = tool_invoke_handler(research_task, context)
    assert research_result["output"]["real"] is True
    assert "hubspot-crm-ingress" in search_authority.request.call_args.kwargs["url"]

    upsert_task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="crm upsert",
        description="crm upsert",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "gtm.crm_upsert",
                "input": {
                    "record_type": "contact",
                    "data": {"email": "buyer@example.com", "firstname": "Jane"},
                },
                "idempotency_key": "upsert-1",
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "credential_type": "api_key",
            },
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["gtm.crm_upsert"],
                    "reason": "integration test",
                    "approved_by": "integration",
                }
            },
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    upsert_result = tool_invoke_handler(upsert_task, context)
    assert upsert_result["output"]["real"] is True
    assert upsert_result["output"]["status"] == "upserted_real"


def test_crm_research_falls_back_when_adapter_returns_error(
    integration_env: None,
    hubspot_runtime_settings: None,
    pg_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    _store_hubspot_credential(pg_session, tenant_id=tenant_id)
    pg_session.commit()

    authority = _egress_spy(status_code=401, body='{"detail":"invalid HubSpot token"}')
    monkeypatch.setattr(
        "backend.services.plugins.crm_client.get_default_network_egress_authority",
        lambda: authority,
    )
    monkeypatch.setattr(
        "backend.services.tools.runtime_authority.validate_capability_action_authority",
        lambda **kwargs: None,
    )

    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="crm research",
        description="crm research",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "sales.research",
                "input": {"lead": {"company": "Acme"}},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "credential_type": "api_key",
            },
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    result = tool_invoke_handler(
        task,
        {
            "worker_id": "worker-test",
            "tenant_id": tenant_id,
            "lease_id": str(uuid.uuid4()),
            "session_factory": lambda: pg_session,
        },
    )
    assert result["output"]["real"] is True
    assert result["output"]["source"] == "ajenda_brain"
    assert result["output"]["external_attempt_failed"] is True
    assert result["output"]["hybrid_mode"] is True
