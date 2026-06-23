"""Integration test: human-first customer loop (signup → verify → OIDC session)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.main import create_app
from backend.services.oidc_login_service import OidcLoginService
from tests.integration.auth.oidc_test_support import (
    TEST_REDIRECT_URI,
    bearer_auth,
    client_ip_headers,
    configure_oidc_integration_env,
    idem_headers,
    mock_oidc_metadata,
    pkce_pair,
    unique_oidc_subject,
)

pytestmark = pytest.mark.integration


class TestHumanCustomerLoopReal:
    def test_signup_verify_oidc_session_without_api_key_promote(
        self,
        monkeypatch: pytest.MonkeyPatch,
        integration_env: None,
    ) -> None:
        configure_oidc_integration_env(monkeypatch)
        get_settings.cache_clear()
        email = f"human-loop-{uuid.uuid4().hex[:8]}@example.com"
        subject = unique_oidc_subject()
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
            patch.object(
                OidcLoginService,
                "_id_token_validator",
                return_value=SimpleNamespace(
                    validate=lambda *_args, **_kwargs: SimpleNamespace(
                        sub=subject,
                        email=email,
                        email_verified=True,
                        nonce="nonce-human",
                    )
                ),
            ),
        ):
            with TestClient(create_app()) as client:
                signup = client.post(
                    "/v1/onboarding/signup",
                    json={"org_name": "Human Loop Co", "email": email},
                    headers={**idem_headers(), **client_ip_headers()},
                )
                assert signup.status_code == 201, signup.text
                token = signup.json()["verification_token"]
                assert token

                verify = client.post(
                    "/v1/onboarding/verify-email",
                    json={"token": token},
                    headers={**idem_headers(), **client_ip_headers()},
                )
                assert verify.status_code == 200, verify.text

                start = client.post(
                    "/v1/auth/oidc/start",
                    json={"redirect_uri": TEST_REDIRECT_URI, "code_challenge": challenge},
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
                        "redirect_uri": TEST_REDIRECT_URI,
                    },
                    headers=client_ip_headers(),
                )
                assert callback.status_code == 200, callback.text
                session = callback.json()
                access_token = session["access_token"]
                session_tenant_id = session["tenant_id"]

                me = client.get("/v1/account/me", headers=bearer_auth(session_tenant_id, access_token))
                assert me.status_code == 200, me.text
                assert me.json()["membership"]["email"] == email

                usage = client.get("/v1/account/usage", headers=bearer_auth(session_tenant_id, access_token))
                assert usage.status_code == 200, usage.text
                assert "missions_created" in usage.json()["usage"]

                billing = client.get("/v1/account/billing", headers=bearer_auth(session_tenant_id, access_token))
                assert billing.status_code == 200, billing.text
