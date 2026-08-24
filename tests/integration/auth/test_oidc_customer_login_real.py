"""Integration tests: OIDC customer login over HTTP with real Postgres."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.domain.customer_auth_session import CustomerAuthSession
from backend.domain.oidc_login_intent import OidcLoginIntent
from backend.main import create_app
from backend.services.oidc_login_service import OidcLoginService
from tests.integration.auth.oidc_test_support import (
    TEST_REDIRECT_URI,
    bearer_auth,
    client_ip_headers,
    configure_oidc_integration_env,
    idem_headers,
    mock_oidc_metadata,
    oidc_provider_patches,
    pkce_pair,
    unique_oidc_subject,
)

pytestmark = pytest.mark.integration


def _signup_and_verify(client: TestClient, email: str) -> tuple[str, str]:
    signup = client.post(
        "/v1/onboarding/signup",
        json={"org_name": "OIDC Integration Co", "email": email},
        headers={**idem_headers(), **client_ip_headers()},
    )
    assert signup.status_code == 201, signup.text
    code = signup.json()["verification_code"]
    assert code and len(code) == 6

    verify = client.post(
        "/v1/onboarding/verify-email",
        json={"email": email, "code": code},
        headers={**idem_headers(), **client_ip_headers()},
    )
    assert verify.status_code == 200, verify.text
    return verify.json()["tenant_id"], email


class TestOidcCustomerLoginHttpReal:
    def test_oidc_config_enabled_when_login_ready(
        self,
        monkeypatch: pytest.MonkeyPatch,
        integration_env: None,
    ) -> None:
        configure_oidc_integration_env(monkeypatch)
        get_settings.cache_clear()

        metadata = mock_oidc_metadata()
        with patch(
            "backend.services.oidc_login_service.OidcDiscoveryClient.get_metadata",
            return_value=metadata,
        ):
            with TestClient(create_app()) as client:
                response = client.get("/v1/auth/oidc/config")

        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert body["provider"] == "google"
        assert body["client_id"] == "integration-client-id"

    def test_http_oidc_login_refresh_logout_loop(
        self,
        monkeypatch: pytest.MonkeyPatch,
        integration_env: None,
        pg_engine: object,
    ) -> None:
        configure_oidc_integration_env(monkeypatch)
        monkeypatch.setenv("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN", "true")
        monkeypatch.setenv("AJENDA_EMAIL_PROVIDER", "noop")
        get_settings.cache_clear()
        email = f"oidc-http-{uuid.uuid4().hex[:8]}@example.com"
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
                        nonce="nonce-http",
                    )
                ),
            ),
        ):
            with TestClient(create_app()) as client:
                tenant_id, _ = _signup_and_verify(client, email)

                start = client.post(
                    "/v1/auth/oidc/start",
                    json={"redirect_uri": TEST_REDIRECT_URI, "code_challenge": challenge},
                    headers=client_ip_headers(),
                )
                assert start.status_code == 200, start.text
                start_body = start.json()
                login_intent_id = start_body["login_intent_id"]
                assert "authorize" in start_body["authorization_url"]

                with Session(pg_engine) as db_session:
                    intent = db_session.get(OidcLoginIntent, uuid.UUID(login_intent_id))
                    assert intent is not None
                    assert intent.code_challenge == challenge
                    assert intent.consumed_at is None

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
                session_body = callback.json()
                assert session_body["tenant_id"] == tenant_id
                assert session_body["email"] == email
                assert session_body["access_token"]
                assert session_body["refresh_token"]

                session_tenant_id = session_body["tenant_id"]
                me = client.get(
                    "/v1/account/me",
                    headers=bearer_auth(session_tenant_id, session_body["access_token"]),
                )
                assert me.status_code == 200, me.text
                me_body = me.json()
                assert me_body["membership"]["email"] == email
                assert me_body["tenant"]["plan"] == "free"

                billing = client.get(
                    "/v1/account/billing",
                    headers=bearer_auth(session_tenant_id, session_body["access_token"]),
                )
                assert billing.status_code == 200, billing.text

                refresh = client.post(
                    "/v1/auth/session/refresh",
                    json={"refresh_token": session_body["refresh_token"]},
                    headers=client_ip_headers(),
                )
                assert refresh.status_code == 200, refresh.text
                refreshed = refresh.json()
                assert refreshed["access_token"]
                assert refreshed["refresh_token"] != session_body["refresh_token"]

                logout = client.post(
                    "/v1/auth/logout",
                    headers=bearer_auth(session_tenant_id, refreshed["access_token"]),
                )
                assert logout.status_code == 200, logout.text

                me_revoked = client.get(
                    "/v1/account/me",
                    headers=bearer_auth(session_tenant_id, refreshed["access_token"]),
                )
                assert me_revoked.status_code == 401

                with Session(pg_engine) as db_session:
                    consumed = db_session.get(OidcLoginIntent, uuid.UUID(login_intent_id))
                    assert consumed is not None
                    assert consumed.consumed_at is not None
                    sessions = (
                        db_session.execute(
                            select(CustomerAuthSession).where(
                                CustomerAuthSession.tenant_id == uuid.UUID(session_tenant_id)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert sessions
                    assert all(row.revoked_at is not None for row in sessions)

    def test_http_oidc_callback_activates_pending_member_without_email_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
        integration_env: None,
    ) -> None:
        """A provider-verified email is an independent proof of email ownership."""
        configure_oidc_integration_env(monkeypatch)
        monkeypatch.setenv("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN", "true")
        monkeypatch.setenv("AJENDA_EMAIL_PROVIDER", "noop")
        get_settings.cache_clear()
        email = f"oidc-pending-{uuid.uuid4().hex[:8]}@example.com"
        verifier, challenge = pkce_pair()

        with TestClient(create_app()) as client:
            signup = client.post(
                "/v1/onboarding/signup",
                json={"org_name": "Pending OIDC Co", "email": email},
                headers={**idem_headers(), **client_ip_headers()},
            )
            assert signup.status_code == 201
            assert signup.json()["status"] == "verification_required"

            with oidc_provider_patches(email=email):
                start = client.post(
                    "/v1/auth/oidc/start",
                    json={"redirect_uri": TEST_REDIRECT_URI, "code_challenge": challenge},
                    headers=client_ip_headers(),
                )
                assert start.status_code == 200
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
            assert callback.json()["tenant_id"]
            assert callback.json()["access_token"]

    def test_http_oidc_callback_rejects_unknown_account(
        self,
        monkeypatch: pytest.MonkeyPatch,
        integration_env: None,
    ) -> None:
        configure_oidc_integration_env(monkeypatch)
        get_settings.cache_clear()
        email = f"oidc-missing-{uuid.uuid4().hex[:8]}@example.com"
        verifier, challenge = pkce_pair()

        with oidc_provider_patches(email=email):
            with TestClient(create_app()) as client:
                start = client.post(
                    "/v1/auth/oidc/start",
                    json={"redirect_uri": TEST_REDIRECT_URI, "code_challenge": challenge},
                    headers=client_ip_headers(),
                )
                assert start.status_code == 200
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

        assert callback.status_code == 404, callback.text
        assert callback.json()["detail"]["code"] == "ACCOUNT_NOT_FOUND"

    def test_http_oidc_callback_rejects_replayed_intent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        integration_env: None,
    ) -> None:
        configure_oidc_integration_env(monkeypatch)
        monkeypatch.setenv("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN", "true")
        monkeypatch.setenv("AJENDA_EMAIL_PROVIDER", "noop")
        get_settings.cache_clear()
        email = f"oidc-replay-{uuid.uuid4().hex[:8]}@example.com"
        verifier, challenge = pkce_pair()

        with oidc_provider_patches(email=email):
            with TestClient(create_app()) as client:
                tenant_id, _ = _signup_and_verify(client, email)

                start = client.post(
                    "/v1/auth/oidc/start",
                    json={"redirect_uri": TEST_REDIRECT_URI, "code_challenge": challenge},
                    headers=client_ip_headers(),
                )
                assert start.status_code == 200
                login_intent_id = start.json()["login_intent_id"]

                payload = {
                    "login_intent_id": login_intent_id,
                    "code": "integration-auth-code",
                    "code_verifier": verifier,
                    "redirect_uri": TEST_REDIRECT_URI,
                }
                first = client.post("/v1/auth/oidc/callback", json=payload, headers=client_ip_headers())
                assert first.status_code == 200, first.text
                assert first.json()["tenant_id"] == tenant_id

                replay = client.post("/v1/auth/oidc/callback", json=payload, headers=client_ip_headers())
                assert replay.status_code == 400, replay.text
