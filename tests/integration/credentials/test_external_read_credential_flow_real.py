"""Credentials API registration for LinkedIn/Salesforce read providers."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from tests.integration.credentials.credential_e2e_support import auth_headers, provision_operational_tenant

pytestmark = pytest.mark.integration


def test_provider_credentials_api_register_linkedin_read(
    integration_env: None,
    pg_engine: object,
    credential_live_onboarding: None,
) -> None:
    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="read-flow-linkedin")

        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
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
    credential_live_onboarding: None,
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
        tenant_id, api_key = provision_operational_tenant(client, prefix="read-flow-salesforce")

        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
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
    credential_live_onboarding: None,
) -> None:
    _ = pg_engine
    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="read-flow-calendar")

        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
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
    credential_live_onboarding: None,
) -> None:
    _ = pg_engine
    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="read-flow-github")

        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
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
