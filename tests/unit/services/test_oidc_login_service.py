"""Unit tests for OIDC customer login orchestration."""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.auth.id_token_validator import IdTokenClaims
from backend.domain.tenant import Tenant
from backend.domain.tenant_member import TenantMember
from backend.services.auth_login_abuse_guard import AuthLoginRateLimitedError
from backend.services.oidc_login_service import (
    OidcAccountNotFoundError,
    OidcAccountPendingVerificationError,
    OidcLoginService,
    OidcLoginValidationError,
    OidcMultipleTenantsError,
)


def _settings(**overrides: object) -> Settings:
    base = {
        "env": "test",
        "oidc_login_enabled": True,
        "oidc_provider": "generic",
        "oidc_client_id": "client-test",
        "oidc_client_secret": "secret-test",
        "oidc_issuer": "https://idp.example.com",
        "oidc_scopes": "openid email profile",
        "oidc_redirect_uri_allowlist": "http://localhost:8080/auth/callback",
        "session_signing_secret": "s" * 40,
        "session_access_ttl_seconds": 3600,
        "session_refresh_ttl_seconds": 604800,
        "oidc_login_intent_ttl_minutes": 10,
    }
    base.update(overrides)
    return Settings.model_construct(**base)


def _member(*, tenant_id: uuid.UUID, email: str = "owner@example.com") -> TenantMember:
    return TenantMember(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        email_raw=email,
        email_canonical=email.lower(),
        role="tenant_owner",
        status="active",
        external_subject_id=None,
    )


def _tenant(tenant_id: uuid.UUID) -> Tenant:
    tenant = Tenant(
        id=tenant_id,
        name="Acme",
        slug="acme",
        plan="free",
        status="active",
    )
    return tenant


def test_public_config_disabled_when_login_not_ready() -> None:
    service = OidcLoginService(MagicMock(spec=Session), settings=_settings(oidc_login_enabled=False))
    config = service.public_config()
    assert config.enabled is False
    assert config.client_id is None


def test_start_login_returns_authorization_url() -> None:
    db = MagicMock(spec=Session)
    service = OidcLoginService(db, settings=_settings())
    metadata = SimpleNamespace(
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
        jwks_uri="https://idp.example.com/jwks",
        issuer="https://idp.example.com",
    )
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")

    created_intent_id = uuid.uuid4()
    with (
        patch.object(service, "_discovery", return_value=SimpleNamespace(get_metadata=lambda: metadata)),
        patch.object(service._abuse, "check_start_ip"),
        patch.object(service._abuse, "record"),
        patch.object(
            service._intents,
            "create",
            return_value=SimpleNamespace(id=created_intent_id),
        ),
    ):
        result = service.start_login(
            redirect_uri="http://localhost:8080/auth/callback",
            code_challenge=challenge,
            client_ip_hash="ip-hash",
        )

    assert result.login_intent_id == str(created_intent_id)
    assert "client-test" in result.authorization_url
    assert "code_challenge=" in result.authorization_url


def test_complete_login_links_member_and_issues_session() -> None:
    db = MagicMock(spec=Session)
    tenant_id = uuid.uuid4()
    member = _member(tenant_id=tenant_id)
    intent = SimpleNamespace(
        id=uuid.uuid4(),
        code_challenge=base64.urlsafe_b64encode(hashlib.sha256(b"verifier-123456789012345678901234567890").digest())
        .decode()
        .rstrip("="),
        redirect_uri="http://localhost:8080/auth/callback",
        nonce="nonce-1",
        client_ip_hash="ip-hash",
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
        consumed_at=None,
    )

    service = OidcLoginService(db, settings=_settings())
    service._intents.get = MagicMock(return_value=intent)  # type: ignore[method-assign]
    service._intents.consume = MagicMock(return_value=intent)  # type: ignore[method-assign]
    service._members.get_active_by_external_subject_id = MagicMock(return_value=None)  # type: ignore[method-assign]
    service._members.list_active_for_email = MagicMock(return_value=[member])  # type: ignore[method-assign]
    service._members.link_external_subject = MagicMock(return_value=member)  # type: ignore[method-assign]
    service._tenants.get = MagicMock(return_value=_tenant(tenant_id))  # type: ignore[method-assign]
    service._sessions.create = MagicMock()  # type: ignore[method-assign]
    service._audit.append = MagicMock()  # type: ignore[method-assign]

    metadata = SimpleNamespace(
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
        jwks_uri="https://idp.example.com/jwks",
        issuer="https://idp.example.com",
    )
    claims = IdTokenClaims(sub="sub-123", email="owner@example.com", email_verified=True, nonce="nonce-1")

    with (
        patch.object(service, "_discovery", return_value=SimpleNamespace(get_metadata=lambda: metadata)),
        patch.object(service, "_exchange_code", return_value={"id_token": "id-token"}),
        patch.object(service, "_id_token_validator", return_value=SimpleNamespace(validate=lambda *_a, **_k: claims)),
        patch.object(service._abuse, "check_callback_ip"),
        patch.object(service._abuse, "check_callback_email"),
        patch.object(service._abuse, "record"),
    ):
        result = service.complete_login(
            login_intent_id=str(intent.id),
            code="auth-code",
            code_verifier="verifier-123456789012345678901234567890",
            redirect_uri="http://localhost:8080/auth/callback",
            client_ip_hash="ip-hash",
        )

    assert result.tenant_id == str(tenant_id)
    assert result.access_token
    assert result.refresh_token
    service._members.link_external_subject.assert_called_once()  # type: ignore[attr-defined]
    service._sessions.create.assert_called_once()  # type: ignore[attr-defined]


def test_complete_login_rejects_invalid_pkce() -> None:
    db = MagicMock(spec=Session)
    service = OidcLoginService(db, settings=_settings())
    intent = SimpleNamespace(
        id=uuid.uuid4(),
        code_challenge="bad-challenge",
        redirect_uri="http://localhost:8080/auth/callback",
        nonce="nonce-1",
        client_ip_hash="ip-hash",
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
        consumed_at=None,
    )
    service._intents.get = MagicMock(return_value=intent)  # type: ignore[method-assign]

    with (
        patch.object(service._abuse, "check_callback_ip"),
        patch.object(service._abuse, "record"),
        pytest.raises(OidcLoginValidationError, match="PKCE"),
    ):
        service.complete_login(
            login_intent_id=str(intent.id),
            code="auth-code",
            code_verifier="verifier-123456789012345678901234567890",
            redirect_uri="http://localhost:8080/auth/callback",
            client_ip_hash="ip-hash",
        )


def test_complete_login_fails_when_no_membership() -> None:
    db = MagicMock(spec=Session)
    service = OidcLoginService(db, settings=_settings())
    intent = SimpleNamespace(
        id=uuid.uuid4(),
        code_challenge=base64.urlsafe_b64encode(hashlib.sha256(b"verifier-123456789012345678901234567890").digest())
        .decode()
        .rstrip("="),
        redirect_uri="http://localhost:8080/auth/callback",
        nonce="nonce-1",
        client_ip_hash="ip-hash",
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
        consumed_at=None,
    )
    service._intents.get = MagicMock(return_value=intent)  # type: ignore[method-assign]
    service._members.get_active_by_external_subject_id = MagicMock(return_value=None)  # type: ignore[method-assign]
    service._members.list_active_for_email = MagicMock(return_value=[])  # type: ignore[method-assign]
    service._members.get_owner_by_email_canonical = MagicMock(return_value=None)  # type: ignore[method-assign]
    claims = IdTokenClaims(sub="sub-404", email="missing@example.com", email_verified=True, nonce="nonce-1")

    with (
        patch.object(service, "_exchange_code", return_value={"id_token": "id-token"}),
        patch.object(service, "_id_token_validator", return_value=SimpleNamespace(validate=lambda *_a, **_k: claims)),
        patch.object(service._abuse, "check_callback_ip"),
        patch.object(service._abuse, "check_callback_email"),
        patch.object(service._abuse, "record"),
        pytest.raises(OidcAccountNotFoundError),
    ):
        service.complete_login(
            login_intent_id=str(intent.id),
            code="auth-code",
            code_verifier="verifier-123456789012345678901234567890",
            redirect_uri="http://localhost:8080/auth/callback",
            client_ip_hash="ip-hash",
        )


def test_start_login_rejects_disallowed_redirect_uri() -> None:
    service = OidcLoginService(MagicMock(spec=Session), settings=_settings())
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(b"verifier-123456789012345678901234567890").digest())
        .decode()
        .rstrip("=")
    )
    with pytest.raises(OidcLoginValidationError, match="redirect_uri is not allowed"):
        service.start_login(
            redirect_uri="https://evil.example/auth/callback",  # noqa: S106 — intentional disallowed URI
            code_challenge=challenge,
            client_ip_hash="ip-hash",
        )


def test_start_login_rejects_invalid_code_challenge() -> None:
    service = OidcLoginService(MagicMock(spec=Session), settings=_settings())
    with pytest.raises(OidcLoginValidationError, match="code_challenge"):
        service.start_login(
            redirect_uri="http://localhost:8080/auth/callback",
            code_challenge="not-valid",
            client_ip_hash="ip-hash",
        )


def test_complete_login_rejects_redirect_uri_mismatch() -> None:
    db = MagicMock(spec=Session)
    service = OidcLoginService(db, settings=_settings())
    intent = SimpleNamespace(
        id=uuid.uuid4(),
        code_challenge=base64.urlsafe_b64encode(hashlib.sha256(b"verifier-123456789012345678901234567890").digest())
        .decode()
        .rstrip("="),
        redirect_uri="http://localhost:8080/auth/callback",
        nonce="nonce-1",
        client_ip_hash="ip-hash",
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
        consumed_at=None,
    )
    service._intents.get = MagicMock(return_value=intent)  # type: ignore[method-assign]

    with (
        patch.object(service._abuse, "check_callback_ip"),
        patch.object(service._abuse, "record"),
        pytest.raises(OidcLoginValidationError, match="redirect_uri mismatch"),
    ):
        service.complete_login(
            login_intent_id=str(intent.id),
            code="auth-code",
            code_verifier="verifier-123456789012345678901234567890",
            redirect_uri="http://localhost:8080/other-callback",
            client_ip_hash="ip-hash",
        )


def test_complete_login_rejects_client_ip_mismatch() -> None:
    db = MagicMock(spec=Session)
    service = OidcLoginService(db, settings=_settings())
    intent = SimpleNamespace(
        id=uuid.uuid4(),
        code_challenge=base64.urlsafe_b64encode(hashlib.sha256(b"verifier-123456789012345678901234567890").digest())
        .decode()
        .rstrip("="),
        redirect_uri="http://localhost:8080/auth/callback",
        nonce="nonce-1",
        client_ip_hash="ip-hash",
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
        consumed_at=None,
    )
    service._intents.get = MagicMock(return_value=intent)  # type: ignore[method-assign]

    with (
        patch.object(service._abuse, "check_callback_ip"),
        patch.object(service._abuse, "record"),
        pytest.raises(OidcLoginValidationError, match="client mismatch"),
    ):
        service.complete_login(
            login_intent_id=str(intent.id),
            code="auth-code",
            code_verifier="verifier-123456789012345678901234567890",
            redirect_uri="http://localhost:8080/auth/callback",
            client_ip_hash="other-ip",
        )


def test_complete_login_requires_email_verification_for_pending_member() -> None:
    db = MagicMock(spec=Session)
    tenant_id = uuid.uuid4()
    pending = _member(tenant_id=tenant_id)
    pending.status = "pending_verification"  # type: ignore[attr-defined]
    service = OidcLoginService(db, settings=_settings())
    intent = SimpleNamespace(
        id=uuid.uuid4(),
        code_challenge=base64.urlsafe_b64encode(hashlib.sha256(b"verifier-123456789012345678901234567890").digest())
        .decode()
        .rstrip("="),
        redirect_uri="http://localhost:8080/auth/callback",
        nonce="nonce-1",
        client_ip_hash="ip-hash",
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
        consumed_at=None,
    )
    service._intents.get = MagicMock(return_value=intent)  # type: ignore[method-assign]
    service._members.get_active_by_external_subject_id = MagicMock(return_value=None)  # type: ignore[method-assign]
    service._members.list_active_for_email = MagicMock(return_value=[])  # type: ignore[method-assign]
    service._members.get_owner_by_email_canonical = MagicMock(return_value=pending)  # type: ignore[method-assign]
    claims = IdTokenClaims(sub="sub-pending", email="owner@example.com", email_verified=True, nonce="nonce-1")

    with (
        patch.object(service, "_exchange_code", return_value={"id_token": "id-token"}),
        patch.object(service, "_id_token_validator", return_value=SimpleNamespace(validate=lambda *_a, **_k: claims)),
        patch.object(service._abuse, "check_callback_ip"),
        patch.object(service._abuse, "check_callback_email"),
        patch.object(service._abuse, "record"),
        pytest.raises(OidcAccountPendingVerificationError),
    ):
        service.complete_login(
            login_intent_id=str(intent.id),
            code="auth-code",
            code_verifier="verifier-123456789012345678901234567890",
            redirect_uri="http://localhost:8080/auth/callback",
            client_ip_hash="ip-hash",
        )


def test_complete_login_returns_multiple_tenant_choices() -> None:
    db = MagicMock(spec=Session)
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    member_a = _member(tenant_id=tenant_a, email="owner@example.com")
    member_b = _member(tenant_id=tenant_b, email="owner@example.com")
    service = OidcLoginService(db, settings=_settings())
    intent = SimpleNamespace(
        id=uuid.uuid4(),
        code_challenge=base64.urlsafe_b64encode(hashlib.sha256(b"verifier-123456789012345678901234567890").digest())
        .decode()
        .rstrip("="),
        redirect_uri="http://localhost:8080/auth/callback",
        nonce="nonce-1",
        client_ip_hash="ip-hash",
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
        consumed_at=None,
    )
    service._intents.get = MagicMock(return_value=intent)  # type: ignore[method-assign]
    service._members.get_active_by_external_subject_id = MagicMock(return_value=None)  # type: ignore[method-assign]
    service._members.list_active_for_email = MagicMock(return_value=[member_a, member_b])  # type: ignore[method-assign]
    service._tenants.get = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda tenant_id: _tenant(tenant_id) if tenant_id in {tenant_a, tenant_b} else None
    )
    claims = IdTokenClaims(sub="sub-multi", email="owner@example.com", email_verified=True, nonce="nonce-1")

    with (
        patch.object(service, "_exchange_code", return_value={"id_token": "id-token"}),
        patch.object(service, "_id_token_validator", return_value=SimpleNamespace(validate=lambda *_a, **_k: claims)),
        patch.object(service._abuse, "check_callback_ip"),
        patch.object(service._abuse, "check_callback_email"),
        patch.object(service._abuse, "record"),
        pytest.raises(OidcMultipleTenantsError) as exc_info,
    ):
        service.complete_login(
            login_intent_id=str(intent.id),
            code="auth-code",
            code_verifier="verifier-123456789012345678901234567890",
            redirect_uri="http://localhost:8080/auth/callback",
            client_ip_hash="ip-hash",
        )

    assert len(exc_info.value.tenants) == 2


def test_refresh_session_enforces_ip_rate_limit() -> None:
    service = OidcLoginService(MagicMock(spec=Session), settings=_settings())
    with (
        patch.object(
            service._abuse,
            "check_refresh_ip",
            side_effect=AuthLoginRateLimitedError(dimension="ip", route="/v1/auth/session/refresh"),
        ),
        pytest.raises(AuthLoginRateLimitedError),
    ):
        service.refresh_session(refresh_token="refresh-token", client_ip_hash="ip-hash")
