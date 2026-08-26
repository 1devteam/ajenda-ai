"""Real PostgreSQL concurrency proof for single-use credential transitions."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings
from backend.auth.principal import MachinePrincipal, PrincipalType
from backend.db.tenant_session import activate_tenant_session
from backend.domain.api_key_record import ApiKeyRecordModel
from backend.domain.customer_auth_session import CustomerAuthSession
from backend.repositories.customer_auth_session_repository import CustomerAuthSessionRepository
from backend.repositories.tenant_member_repository import TenantMemberRepository
from backend.services.oidc_login_service import OidcLoginService, OidcLoginValidationError
from backend.services.tenant_onboarding_orchestrator import (
    BootstrapPromotionError,
    InvalidVerificationTokenError,
    TenantOnboardingOrchestrator,
)

pytestmark = pytest.mark.integration


def _settings() -> Settings:
    return Settings.model_construct(
        env="test",
        signup_enabled=True,
        signup_expose_verification_token=True,
        signup_email_limit_per_hour=100,
        signup_resend_email_limit_per_hour=100,
        signup_verify_failures_per_hour=100,
        signup_bootstrap_key_ttl_hours=72,
        signup_verification_ttl_hours=24,
        email_provider="noop",
        oidc_login_enabled=True,
        oidc_provider="google",
        oidc_client_id="single-use-integration-client",
        oidc_client_secret="single-use-integration-secret",
        oidc_issuer="https://idp.integration.example.com",
        oidc_id_token_audience="single-use-integration-client",
        oidc_redirect_uri_allowlist="http://localhost:8080/auth/callback",
        session_signing_secret="single-use-session-signing-secret-48-characters-minimum",
        session_access_ttl_seconds=3600,
        session_refresh_ttl_seconds=604800,
        oidc_login_intent_ttl_minutes=10,
        auth_login_start_ip_limit_per_hour=100,
        auth_login_callback_ip_limit_per_hour=100,
        auth_login_callback_email_limit_per_hour=100,
        auth_login_refresh_ip_limit_per_hour=100,
    )


def _session_factory(pg_engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=pg_engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


def _signup(factory: sessionmaker[Session], *, prefix: str):
    session = factory()
    try:
        email = f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"
        orchestrator = TenantOnboardingOrchestrator(session, settings=_settings())
        receipt = orchestrator.begin_signup(
            org_name=f"{prefix} Co",
            email=email,
            slug=None,
            client_ip_hash=f"{prefix}-setup-ip",
        )
        session.commit()
        return receipt
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _verify(factory: sessionmaker[Session], *, email: str, code: str):
    session = factory()
    try:
        result = TenantOnboardingOrchestrator(session, settings=_settings()).complete_verification(
            email=email,
            code=code,
            client_ip_hash="single-use-setup-ip",
        )
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def test_verification_token_mints_exactly_one_bootstrap_key_under_contention(pg_engine) -> None:
    factory = _session_factory(pg_engine)
    receipt = _signup(factory, prefix="verify-race")
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    guard = threading.Lock()

    def contender() -> None:
        session = factory()
        try:
            barrier.wait()
            TenantOnboardingOrchestrator(session, settings=_settings()).complete_verification(
                email=receipt.email.canonical,
                code=receipt.verification_token_plaintext,
                client_ip_hash="verify-race-ip",
            )
            session.commit()
            outcome = "success"
        except InvalidVerificationTokenError:
            session.rollback()
            outcome = "consumed"
        finally:
            session.close()
        with guard:
            outcomes.append(outcome)

    threads = [threading.Thread(target=contender) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("success") == 1
    assert outcomes.count("consumed") == 1

    check = factory()
    try:
        member = TenantMemberRepository(check).get_active_owner_for_tenant(receipt.tenant_id)
        assert member is not None
        assert member.verification_token_hash is None
        bootstrap_keys = list(
            check.scalars(
                select(ApiKeyRecordModel).where(
                    ApiKeyRecordModel.tenant_id == str(receipt.tenant_id),
                    ApiKeyRecordModel.purpose == "bootstrap",
                )
            ).all()
        )
        assert len(bootstrap_keys) == 1
    finally:
        check.close()


def test_bootstrap_key_mints_exactly_one_operational_key_under_contention(pg_engine) -> None:
    factory = _session_factory(pg_engine)
    receipt = _signup(factory, prefix="bootstrap-race")
    verification = _verify(
        factory,
        email=receipt.email.canonical,
        code=receipt.verification_token_plaintext,
    )
    principal = MachinePrincipal(
        subject_id=f"machine:{verification.key_id}",
        tenant_id=str(verification.tenant_id),
        principal_type=PrincipalType.MACHINE,
        roles=("signup_bootstrap",),
        permissions=frozenset(),
        key_id=verification.key_id,
    )
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    guard = threading.Lock()

    def contender() -> None:
        session = factory()
        try:
            activate_tenant_session(session, str(verification.tenant_id))
            barrier.wait()
            TenantOnboardingOrchestrator(session, settings=_settings()).promote_bootstrap_key(principal=principal)
            session.commit()
            outcome = "success"
        except BootstrapPromotionError:
            session.rollback()
            outcome = "consumed"
        finally:
            session.close()
        with guard:
            outcomes.append(outcome)

    threads = [threading.Thread(target=contender) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("success") == 1
    assert outcomes.count("consumed") == 1

    check = factory()
    try:
        activate_tenant_session(check, str(verification.tenant_id))
        keys = list(
            check.scalars(
                select(ApiKeyRecordModel).where(ApiKeyRecordModel.tenant_id == str(verification.tenant_id))
            ).all()
        )
        operational = [record for record in keys if record.purpose == "operational" and not record.revoked]
        bootstrap = [record for record in keys if record.key_id == verification.key_id]
        assert len(operational) == 1
        assert len(bootstrap) == 1
        assert bootstrap[0].revoked is True
    finally:
        check.close()


def test_refresh_token_mints_exactly_one_successor_session_under_contention(pg_engine) -> None:
    factory = _session_factory(pg_engine)
    receipt = _signup(factory, prefix="refresh-race")
    _verify(
        factory,
        email=receipt.email.canonical,
        code=receipt.verification_token_plaintext,
    )

    setup = factory()
    refresh_token = f"refresh-{uuid.uuid4().hex}-{uuid.uuid4().hex}"
    try:
        member = TenantMemberRepository(setup).get_active_owner_for_tenant(receipt.tenant_id)
        assert member is not None
        now = datetime.now(tz=UTC)
        CustomerAuthSessionRepository(setup).create(
            member_id=member.id,
            tenant_id=member.tenant_id,
            access_jti=uuid.uuid4().hex,
            refresh_token_hash=OidcLoginService._hash_refresh_token(refresh_token),
            expires_at=now + timedelta(hours=1),
            refresh_expires_at=now + timedelta(days=1),
            client_ip_hash="refresh-race-setup-ip",
        )
        member_id = member.id
        setup.commit()
    except Exception:
        setup.rollback()
        raise
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    guard = threading.Lock()

    def contender() -> None:
        session = factory()
        try:
            barrier.wait()
            OidcLoginService(session, settings=_settings()).refresh_session(
                refresh_token=refresh_token,
                client_ip_hash="refresh-race-ip",
            )
            session.commit()
            outcome = "success"
        except OidcLoginValidationError:
            session.rollback()
            outcome = "consumed"
        finally:
            session.close()
        with guard:
            outcomes.append(outcome)

    threads = [threading.Thread(target=contender) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("success") == 1
    assert outcomes.count("consumed") == 1

    check = factory()
    try:
        sessions = list(
            check.scalars(select(CustomerAuthSession).where(CustomerAuthSession.member_id == member_id)).all()
        )
        active = [record for record in sessions if record.revoked_at is None]
        revoked = [record for record in sessions if record.revoked_at is not None]
        assert len(active) == 1
        assert len(revoked) == 1
        assert len(sessions) == 2
    finally:
        check.close()
