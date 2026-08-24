"""Credentials API RBAC over HTTP with real Postgres (session + API key principals)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.services.oidc_login_service import OidcLoginService
from tests.integration.auth.oidc_test_support import (
    bearer_auth,
    client_ip_headers,
    configure_oidc_integration_env,
    idem_headers,
    mock_oidc_metadata,
    oidc_provider_patches,
    pkce_pair,
    unique_oidc_subject,
)
from tests.integration.credentials.credential_e2e_support import auth_headers, provision_operational_tenant

pytestmark = pytest.mark.integration


def _signup_verify_bootstrap(
    client: TestClient,
    *,
    prefix: str,
    email: str | None = None,
) -> tuple[str, str, str]:
    resolved_email = email or f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"
    signup = client.post(
        "/v1/onboarding/signup",
        json={"org_name": "Credential RBAC Co", "email": resolved_email},
        headers={**idem_headers(), **client_ip_headers()},
    )
    assert signup.status_code == 201, signup.text
    code = signup.json()["verification_code"]
    assert code and len(code) == 6
    verify = client.post(
        "/v1/onboarding/verify-email",
        json={"email": resolved_email, "code": code},
        headers={**idem_headers(), **client_ip_headers()},
    )
    assert verify.status_code == 200, verify.text
    return verify.json()["tenant_id"], resolved_email, verify.json()["api_key"]


def test_bootstrap_api_key_denied_credentials_manage(
    credential_live_onboarding: None,
    integration_env: None,
    pg_engine: object,
) -> None:
    with TestClient(create_app()) as client:
        tenant_id, _email, bootstrap_key = _signup_verify_bootstrap(client, prefix="cred-rbac-bootstrap")
        response = client.post(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=bootstrap_key),
            json={
                "credential_id": "gmail-email",
                "provider": "external_email",
                "integration": "gmail",
                "secret_value": "bootstrap-should-not-register",
            },
        )
    assert response.status_code == 403, response.text


def test_operational_api_key_allowed_credentials_manage(
    credential_live_onboarding: None,
    integration_env: None,
    pg_engine: object,
) -> None:
    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="cred-rbac-operational")
        response = client.post(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={
                "credential_id": "gmail-email",
                "provider": "external_email",
                "integration": "gmail",
                "secret_value": "operational-api-key-registration",
            },
        )
    assert response.status_code == 201, response.text
    assert response.json()["credential"]["credential_id"] == "gmail-email"


def test_oidc_session_allowed_credentials_manage(
    credential_live_onboarding: None,
    integration_env: None,
    pg_engine: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_oidc_integration_env(monkeypatch)
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", "integration-google-client-id")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", "integration-google-client-secret")
    from backend.app.config import get_settings

    get_settings.cache_clear()

    email = f"cred-rbac-oidc-{uuid.uuid4().hex[:8]}@example.com"
    verifier, challenge = pkce_pair()
    metadata = mock_oidc_metadata()

    with (
        patch(
            "backend.services.oidc_login_service.OidcDiscoveryClient.get_metadata",
            return_value=metadata,
        ),
        patch.object(
            OidcLoginService,
            "_exchange_code",
            return_value={"id_token": "integration-id-token", "access_token": "integration-access-token"},
        ),
        oidc_provider_patches(email=email, sub=unique_oidc_subject()),
    ):
        with TestClient(create_app()) as client:
            tenant_id, _email, _bootstrap_key = _signup_verify_bootstrap(
                client,
                prefix="cred-rbac-oidc",
                email=email,
            )

            start = client.post(
                "/v1/auth/oidc/start",
                json={"redirect_uri": "http://localhost:8080/auth/callback", "code_challenge": challenge},
                headers=client_ip_headers(),
            )
            assert start.status_code == 200, start.text
            login_intent_id = start.json()["login_intent_id"]

            callback = client.post(
                "/v1/auth/oidc/callback",
                json={
                    "login_intent_id": login_intent_id,
                    "code": "integration-auth-code",
                    "code_verifier": verifier,
                    "redirect_uri": "http://localhost:8080/auth/callback",
                },
                headers=client_ip_headers(),
            )
            assert callback.status_code == 200, callback.text
            session = callback.json()
            session_headers = bearer_auth(tenant_id, session["access_token"])

            authorize = client.get(
                "/v1/account/provider-credentials/gmail/oauth/authorize-url",
                headers=session_headers,
            )
            assert authorize.status_code == 200, authorize.text
            assert authorize.json()["state"]

            create = client.post(
                "/v1/account/provider-credentials",
                headers=session_headers,
                json={
                    "credential_id": "gmail-email",
                    "provider": "external_email",
                    "integration": "gmail",
                    "secret_value": "oidc-session-registration",
                },
            )
            assert create.status_code == 201, create.text
            assert create.json()["credential"]["credential_id"] == "gmail-email"
