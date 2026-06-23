"""Shared helpers for OIDC integration tests."""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from backend.auth.id_token_validator import IdTokenClaims
from backend.services.oidc_login_service import OidcLoginService

TEST_CLIENT_IP = "203.0.113.55"
TEST_REDIRECT_URI = "http://localhost:8080/auth/callback"


def unique_oidc_subject() -> str:
    """Return a fresh Google subject for each test to avoid cross-test linking."""
    return f"google-sub-{uuid.uuid4().hex}"


def client_ip_headers() -> dict[str, str]:
    return {"X-Forwarded-For": TEST_CLIENT_IP}


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest()).decode("ascii").rstrip("=")
    return verifier, challenge


def idem_headers() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def bearer_auth(tenant_id: str, access_token: str) -> dict[str, str]:
    return {
        "X-Tenant-Id": tenant_id,
        "Authorization": f"Bearer {access_token}",
        **client_ip_headers(),
    }


def mock_oidc_metadata() -> SimpleNamespace:
    return SimpleNamespace(
        issuer="https://idp.integration.example.com",
        authorization_endpoint="https://idp.integration.example.com/authorize",
        token_endpoint="https://idp.integration.example.com/token",
        jwks_uri="https://idp.integration.example.com/jwks",
    )


def mock_id_token_claims(*, email: str, sub: str, nonce: str | None = "nonce-integration") -> IdTokenClaims:
    return IdTokenClaims(
        sub=sub,
        email=email,
        email_verified=True,
        nonce=nonce,
    )


def configure_oidc_integration_env(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_ENV", "test")
    monkeypatch.setenv("AJENDA_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN", "true")
    monkeypatch.setenv("AJENDA_EMAIL_PROVIDER", "noop")
    monkeypatch.setenv("AJENDA_OIDC_LOGIN_ENABLED", "true")
    monkeypatch.setenv("AJENDA_OIDC_PROVIDER", "google")
    monkeypatch.setenv("AJENDA_OIDC_CLIENT_ID", "integration-client-id")
    monkeypatch.setenv("AJENDA_OIDC_CLIENT_SECRET", "integration-client-secret")
    monkeypatch.setenv("AJENDA_OIDC_ISSUER", "https://idp.integration.example.com")
    monkeypatch.setenv("AJENDA_OIDC_JWKS_URI", "https://idp.integration.example.com/jwks")
    monkeypatch.setenv("AJENDA_OIDC_ID_TOKEN_AUDIENCE", "integration-client-id")
    monkeypatch.setenv("AJENDA_OIDC_REDIRECT_URI_ALLOWLIST", TEST_REDIRECT_URI)
    monkeypatch.setenv("AJENDA_SESSION_SIGNING_SECRET", "integration-session-signing-secret-48chars-min")
    monkeypatch.setenv("AJENDA_SESSION_ACCESS_TTL_SECONDS", "3600")
    monkeypatch.setenv("AJENDA_SESSION_REFRESH_TTL_SECONDS", "604800")
    monkeypatch.setenv("AJENDA_AUTH_LOGIN_START_IP_LIMIT_PER_HOUR", "1000")
    monkeypatch.setenv("AJENDA_AUTH_LOGIN_CALLBACK_IP_LIMIT_PER_HOUR", "1000")
    monkeypatch.setenv("AJENDA_AUTH_LOGIN_CALLBACK_EMAIL_LIMIT_PER_HOUR", "1000")


@contextmanager
def oidc_provider_patches(*, email: str, nonce: str | None = "nonce-integration", sub: str | None = None):
    metadata = mock_oidc_metadata()
    subject = sub or unique_oidc_subject()
    claims = mock_id_token_claims(email=email, sub=subject, nonce=nonce)

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
            return_value=SimpleNamespace(validate=lambda *_args, **_kwargs: claims),
        ),
    ):
        yield
