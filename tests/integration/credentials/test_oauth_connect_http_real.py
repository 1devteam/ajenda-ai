"""Gmail OAuth authorize-url + connect over HTTP with real Postgres."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.services.credentials.gmail_oauth_connect import verify_gmail_oauth_state
from tests.integration.credentials.credential_e2e_support import auth_headers, provision_operational_tenant

pytestmark = pytest.mark.integration


def test_gmail_oauth_authorize_url_returns_signed_state_over_http(
    credential_live_onboarding: None,
    integration_env: None,
    pg_engine: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", "integration-google-client-id")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", "integration-google-client-secret")
    monkeypatch.setenv("AJENDA_SESSION_SIGNING_SECRET", "integration-session-signing-secret-48chars-min")
    from backend.app.config import get_settings

    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="gmail-oauth-http")
        response = client.get(
            "/v1/account/provider-credentials/gmail/oauth/authorize-url",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["authorization_url"].startswith("https://accounts.google.com/")
    assert body["state"]
    assert "." in body["state"]
    claims = verify_gmail_oauth_state(body["state"])
    assert claims.tenant_id == tenant_id
    assert claims.credential_id == "gmail-email"


@patch("backend.api.routes.provider_credentials.exchange_gmail_oauth_code")
def test_gmail_oauth_connect_registers_credential_over_http(
    mock_exchange,
    credential_live_onboarding: None,
    integration_env: None,
    pg_engine: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", "integration-google-client-id")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", "integration-google-client-secret")
    monkeypatch.setenv("AJENDA_SESSION_SIGNING_SECRET", "integration-session-signing-secret-48chars-min")
    from backend.app.config import get_settings

    get_settings.cache_clear()

    mock_exchange.return_value = (
        '{"access_token":"oauth-access","refresh_token":"oauth-refresh","expires_at":"2099-01-01T00:00:00+00:00"}'
    )

    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="gmail-oauth-connect")
        authorize = client.get(
            "/v1/account/provider-credentials/gmail/oauth/authorize-url?credential_id=gmail-email",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
        )
        assert authorize.status_code == 200, authorize.text
        state = authorize.json()["state"]

        connect = client.post(
            "/v1/account/provider-credentials/gmail/oauth/connect",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={"code": "integration-auth-code", "state": state, "credential_id": "gmail-email"},
        )
        assert connect.status_code == 201, connect.text
        credential = connect.json()["credential"]
        assert credential["credential_id"] == "gmail-email"
        assert credential["provider"] == "external_email"
        assert "oauth-access" not in connect.text

        listed = client.get(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
        )
        assert listed.status_code == 200
        assert any(item["credential_id"] == "gmail-email" for item in listed.json()["credentials"])