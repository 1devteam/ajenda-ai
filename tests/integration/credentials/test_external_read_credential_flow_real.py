"""Credentials API registration for LinkedIn/Salesforce read providers."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def read_flow_onboarding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN", "true")
    monkeypatch.setenv("AJENDA_EMAIL_PROVIDER", "noop")
    from backend.app.config import get_settings

    get_settings.cache_clear()


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
    integration_env: None,
    pg_engine: object,
    read_flow_onboarding: None,
) -> None:
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
    integration_env: None,
    pg_engine: object,
    read_flow_onboarding: None,
) -> None:
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


def test_provider_credentials_api_register_google_calendar_read(
    integration_env: None,
    pg_engine: object,
    read_flow_onboarding: None,
) -> None:
    _ = pg_engine
    with TestClient(create_app()) as client:
        tenant_id, api_key = _provision_operational_tenant(client)

        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=_auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={
                "credential_id": "google-calendar-read",
                "provider": "external_read_provider",
                "integration": "google_calendar",
                "secret_value": "tenant-google-calendar-bearer",
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        body = create_resp.json()["credential"]
        assert body["credential_id"] == "google-calendar-read"
        assert "google_calendar.events_read" in body["allowed_actions"]
        assert body["trusted_destination_hosts"] == ["www.googleapis.com"]


def test_provider_credentials_api_register_github_read(
    integration_env: None,
    pg_engine: object,
    read_flow_onboarding: None,
) -> None:
    _ = pg_engine
    with TestClient(create_app()) as client:
        tenant_id, api_key = _provision_operational_tenant(client)

        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=_auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={
                "credential_id": "github-read",
                "provider": "external_read_provider",
                "integration": "github",
                "secret_value": "tenant-github-bearer",
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        body = create_resp.json()["credential"]
        assert body["credential_id"] == "github-read"
        assert "github.repo_read" in body["allowed_actions"]
        assert body["trusted_destination_hosts"] == ["api.github.com"]
        assert "tenant-github-bearer" not in create_resp.text