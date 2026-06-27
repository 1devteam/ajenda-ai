"""Credentials API registration for LinkedIn/Salesforce read providers."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app

pytestmark = pytest.mark.integration


def _auth_headers(*, tenant_id: str, api_key: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-Api-Key": api_key}


def _provision_operational_tenant(client: TestClient) -> tuple[str, str]:
    email = f"read-flow-{uuid.uuid4().hex[:8]}@example.com"
    signup = client.post(
        "/v1/onboarding/signup",
        json={"org_name": "Read Flow Co", "email": email},
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


def test_provider_credentials_api_register_linkedin_read(
    monkeypatch: pytest.MonkeyPatch,
    integration_env: None,
    pg_engine: object,
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
                "credential_id": "linkedin-read",
                "provider": "external_read_provider",
                "integration": "linkedin",
                "secret_value": "tenant-linkedin-bearer",
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        body = create_resp.json()["credential"]
        assert body["credential_id"] == "linkedin-read"
        assert "linkedin.profile_read" in body["allowed_actions"]
        assert body["trusted_destination_hosts"] == ["api.linkedin.com"]
        assert "tenant-linkedin-bearer" not in create_resp.text


def test_provider_credentials_api_register_salesforce_read_from_json_instance_url(
    monkeypatch: pytest.MonkeyPatch,
    integration_env: None,
    pg_engine: object,
) -> None:
    monkeypatch.setenv("AJENDA_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN", "true")
    monkeypatch.setenv("AJENDA_EMAIL_PROVIDER", "noop")
    secret = json.dumps(
        {
            "provider_kind": "salesforce",
            "access_token": "sf-access",
            "refresh_token": "sf-refresh",
            "instance_url": "https://acme.my.salesforce.com",
        }
    )
    with TestClient(create_app()) as client:
        tenant_id, api_key = _provision_operational_tenant(client)

        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=_auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={
                "credential_id": "salesforce-read",
                "provider": "external_read_provider",
                "integration": "salesforce",
                "secret_value": secret,
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        body = create_resp.json()["credential"]
        assert body["credential_id"] == "salesforce-read"
        assert "salesforce.soql_read" in body["allowed_actions"]
        assert body["trusted_destination_hosts"] == ["acme.my.salesforce.com"]
        assert "sf-access" not in create_resp.text