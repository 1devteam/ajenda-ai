"""Integration tests: OIDC login service against real Postgres."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from backend.app.config import Settings
from backend.auth.session_token import SessionTokenService
from backend.domain.customer_auth_session import CustomerAuthSession
from backend.repositories.oidc_login_intent_repository import OidcLoginIntentRepository
from backend.repositories.tenant_member_repository import TenantMemberRepository
from backend.services.oidc_login_service import (
    OidcAccountNotFoundError,
    OidcAccountPendingVerificationError,
    OidcLoginService,
    OidcLoginValidationError,
)
from backend.services.tenant_onboarding_orchestrator import TenantOnboardingOrchestrator
from tests.integration.auth.oidc_test_support import (
    TEST_REDIRECT_URI,
    mock_oidc_metadata,
    pkce_pair,
    unique_oidc_subject,
)

pytestmark = pytest.mark.integration


def _settings() -> Settings:
    return Settings.model_construct(
        env="test",
        signup_enabled=True,
        signup_expose_verification_token=True,
        signup_email_limit_per_hour=30,
        signup_resend_email_limit_per_hour=30,
        signup_verify_failures_per_hour=30,
        signup_bootstrap_key_ttl_hours=72,
        signup_verification_ttl_hours=24,
        email_provider="noop",
        oidc_login_enabled=True,
        oidc_provider="google",
        oidc_client_id="integration-client-id",
        oidc_client_secret="integration-client-secret",
        oidc_issuer="https://idp.integration.example.com",
        oidc_jwks_uri="https://idp.integration.example.com/jwks",
        oidc_id_token_audience="integration-client-id",
        oidc_redirect_uri_allowlist=TEST_REDIRECT_URI,
        session_signing_secret="integration-session-signing-secret-48chars-min",
        session_access_ttl_seconds=3600,
        session_refresh_ttl_seconds=604800,
        oidc_login_intent_ttl_minutes=10,
        auth_login_start_ip_limit_per_hour=100,
        auth_login_callback_ip_limit_per_hour=100,
        auth_login_callback_email_limit_per_hour=100,
    )


def _verified_member(pg_session, *, email: str) -> tuple[uuid.UUID, str]:
    orchestrator = TenantOnboardingOrchestrator(pg_session, settings=_settings())
    receipt = orchestrator.begin_signup(
        org_name="OIDC Service Co",
        email=email,
        slug=None,
        client_ip_hash="integration-ip",
    )
    pg_session.commit()
    orchestrator.complete_verification(
        token=receipt.verification_token_plaintext,
        client_ip_hash="integration-ip",
    )
    pg_session.commit()
    return receipt.tenant_id, email


class TestOidcLoginServiceReal:
    def test_start_login_persists_intent(self, pg_session) -> None:
        service = OidcLoginService(pg_session, settings=_settings())
        verifier, challenge = pkce_pair()
        metadata = mock_oidc_metadata()

        with patch(
            "backend.services.oidc_login_service.OidcDiscoveryClient.get_metadata",
            return_value=metadata,
        ):
            result = service.start_login(
                redirect_uri=TEST_REDIRECT_URI,
                code_challenge=challenge,
                client_ip_hash="integration-ip-hash",
            )
            pg_session.commit()

        intent = OidcLoginIntentRepository(pg_session).get(uuid.UUID(result.login_intent_id))
        assert intent is not None
        assert intent.code_challenge == challenge
        assert intent.redirect_uri == TEST_REDIRECT_URI
        assert intent.nonce

    def test_complete_login_links_subject_and_issues_session(self, pg_session) -> None:
        email = f"oidc-service-{uuid.uuid4().hex[:8]}@example.com"
        subject = unique_oidc_subject()
        tenant_id, _ = _verified_member(pg_session, email=email)
        service = OidcLoginService(pg_session, settings=_settings())
        verifier, challenge = pkce_pair()
        metadata = mock_oidc_metadata()

        with patch(
            "backend.services.oidc_login_service.OidcDiscoveryClient.get_metadata",
            return_value=metadata,
        ):
            started = service.start_login(
                redirect_uri=TEST_REDIRECT_URI,
                code_challenge=challenge,
                client_ip_hash="integration-ip-hash",
            )
            pg_session.commit()

            with (
                patch.object(
                    service,
                    "_exchange_code",
                    return_value={"id_token": "id-token", "access_token": "access-token"},
                ),
                patch.object(
                    service,
                    "_id_token_validator",
                    return_value=SimpleNamespace(
                        validate=lambda *_args, **_kwargs: SimpleNamespace(
                            sub=subject,
                            email=email,
                            email_verified=True,
                            nonce=None,
                        )
                    ),
                ),
            ):
                session = service.complete_login(
                    login_intent_id=started.login_intent_id,
                    code="auth-code",
                    code_verifier=verifier,
                    redirect_uri=TEST_REDIRECT_URI,
                    client_ip_hash="integration-ip-hash",
                )
                pg_session.commit()

        assert session.tenant_id == str(tenant_id)
        assert session.access_token
        assert session.refresh_token

        member = TenantMemberRepository(pg_session).get_active_owner_for_tenant(tenant_id)
        assert member is not None
        assert member.external_subject_id == subject

        token_service = SessionTokenService(
            signing_secret=_settings().session_signing_secret,
            access_ttl_seconds=_settings().session_access_ttl_seconds,
        )
        claims = token_service.validate_access_token(session.access_token)
        db_sessions = (
            pg_session.execute(select(CustomerAuthSession).where(CustomerAuthSession.tenant_id == tenant_id))
            .scalars()
            .all()
        )
        assert len(db_sessions) == 1
        assert db_sessions[0].access_jti == claims.jti
        assert db_sessions[0].revoked_at is None

    def test_complete_login_blocks_pending_verification(self, pg_session) -> None:
        email = f"oidc-pending-svc-{uuid.uuid4().hex[:8]}@example.com"
        subject = unique_oidc_subject()
        orchestrator = TenantOnboardingOrchestrator(pg_session, settings=_settings())
        orchestrator.begin_signup(
            org_name="Pending Service Co",
            email=email,
            slug=None,
            client_ip_hash="integration-ip",
        )
        pg_session.commit()

        service = OidcLoginService(pg_session, settings=_settings())
        verifier, challenge = pkce_pair()

        with patch(
            "backend.services.oidc_login_service.OidcDiscoveryClient.get_metadata",
            return_value=mock_oidc_metadata(),
        ):
            started = service.start_login(
                redirect_uri=TEST_REDIRECT_URI,
                code_challenge=challenge,
                client_ip_hash="integration-ip-hash",
            )
            pg_session.commit()

            with (
                patch.object(
                    service,
                    "_exchange_code",
                    return_value={"id_token": "id-token", "access_token": "access-token"},
                ),
                patch.object(
                    service,
                    "_id_token_validator",
                    return_value=SimpleNamespace(
                        validate=lambda *_args, **_kwargs: SimpleNamespace(
                            sub=subject,
                            email=email,
                            email_verified=True,
                            nonce=None,
                        )
                    ),
                ),
                pytest.raises(OidcAccountPendingVerificationError),
            ):
                service.complete_login(
                    login_intent_id=started.login_intent_id,
                    code="auth-code",
                    code_verifier=verifier,
                    redirect_uri=TEST_REDIRECT_URI,
                    client_ip_hash="integration-ip-hash",
                )

    def test_complete_login_rejects_invalid_pkce(self, pg_session) -> None:
        email = f"oidc-pkce-{uuid.uuid4().hex[:8]}@example.com"
        _verified_member(pg_session, email=email)
        service = OidcLoginService(pg_session, settings=_settings())
        _, challenge = pkce_pair()

        with patch(
            "backend.services.oidc_login_service.OidcDiscoveryClient.get_metadata",
            return_value=mock_oidc_metadata(),
        ):
            started = service.start_login(
                redirect_uri=TEST_REDIRECT_URI,
                code_challenge=challenge,
                client_ip_hash="integration-ip-hash",
            )
            pg_session.commit()

            with pytest.raises(OidcLoginValidationError, match="PKCE"):
                service.complete_login(
                    login_intent_id=started.login_intent_id,
                    code="auth-code",
                    code_verifier="wrong-verifier" * 4,
                    redirect_uri=TEST_REDIRECT_URI,
                    client_ip_hash="integration-ip-hash",
                )

    def test_complete_login_rejects_unknown_email(self, pg_session) -> None:
        email = f"oidc-unknown-{uuid.uuid4().hex[:8]}@example.com"
        subject = unique_oidc_subject()
        service = OidcLoginService(pg_session, settings=_settings())
        verifier, challenge = pkce_pair()

        with patch(
            "backend.services.oidc_login_service.OidcDiscoveryClient.get_metadata",
            return_value=mock_oidc_metadata(),
        ):
            started = service.start_login(
                redirect_uri=TEST_REDIRECT_URI,
                code_challenge=challenge,
                client_ip_hash="integration-ip-hash",
            )
            pg_session.commit()

            with (
                patch.object(
                    service,
                    "_exchange_code",
                    return_value={"id_token": "id-token", "access_token": "access-token"},
                ),
                patch.object(
                    service,
                    "_id_token_validator",
                    return_value=SimpleNamespace(
                        validate=lambda *_args, **_kwargs: SimpleNamespace(
                            sub=subject,
                            email=email,
                            email_verified=True,
                            nonce=None,
                        )
                    ),
                ),
                pytest.raises(OidcAccountNotFoundError),
            ):
                service.complete_login(
                    login_intent_id=started.login_intent_id,
                    code="auth-code",
                    code_verifier=verifier,
                    redirect_uri=TEST_REDIRECT_URI,
                    client_ip_hash="integration-ip-hash",
                )
