"""HubSpot credential registered via Credentials API, then consumed by tool.invoke."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.domain.execution_task import ExecutionTask
from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.main import create_app
from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.workers.handlers.tool_invoke import tool_invoke_handler

pytestmark = pytest.mark.integration


def _auth_headers(*, tenant_id: str, api_key: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-Api-Key": api_key}


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
    email = f"api-invoke-{uuid.uuid4().hex[:8]}@example.com"
    signup = client.post(
        "/v1/onboarding/signup",
        json={"org_name": "API Invoke Co", "email": email},
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


def test_hubspot_api_register_then_crm_research_invokes_adapter(
    monkeypatch: pytest.MonkeyPatch,
    integration_env: None,
    pg_engine: object,
    hubspot_runtime_settings: None,
) -> None:
    monkeypatch.setenv("AJENDA_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN", "true")
    monkeypatch.setenv("AJENDA_EMAIL_PROVIDER", "noop")

    tenant_id: str
    with TestClient(create_app()) as client:
        tenant_id, api_key = _provision_operational_tenant(client)
        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=_auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "integration": "hubspot",
                "secret_value": "api-registered-hubspot-pak",
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        assert "api-registered-hubspot-pak" not in create_resp.text

    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    verify_session = session_factory()
    try:
        row = verify_session.execute(
            select(ProviderRuntimeCredential).where(
                ProviderRuntimeCredential.tenant_id == tenant_id,
                ProviderRuntimeCredential.credential_id == "hubspot-crm",
            )
        ).scalar_one()
        assert row.enabled is True
        assert row.revoked is False
    finally:
        verify_session.close()

    worker_session = session_factory()
    search_authority = _egress_spy(
        status_code=200,
        body='{"results":[{"id":"42"}],"count":1,"source":"hubspot"}',
    )
    monkeypatch.setattr(
        "backend.services.plugins.crm_client.get_default_network_egress_authority",
        lambda: search_authority,
    )
    monkeypatch.setattr(
        "backend.services.tools.runtime_authority.validate_capability_action_authority",
        lambda **kwargs: None,
    )

    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="api path crm research",
        description="credential from API registration",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "crm.research",
                "input": {"lead": {"company": "API Co", "domain": "api.example.com"}},
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
    try:
        result = tool_invoke_handler(
            task,
            {
                "worker_id": "worker-api-invoke",
                "tenant_id": tenant_id,
                "lease_id": str(uuid.uuid4()),
                "session_factory": lambda: worker_session,
            },
        )
        assert result["output"]["real"] is True
        assert "hubspot-crm-ingress" in search_authority.request.call_args.kwargs["url"]
        auth_header = search_authority.request.call_args.kwargs["headers"].get("Authorization", "")
        assert auth_header == "Bearer api-registered-hubspot-pak"
    finally:
        worker_session.close()