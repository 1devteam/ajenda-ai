"""Unit tests for TenantOnboardingOrchestrator."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.app.config import Settings
from backend.auth.principal import MachinePrincipal, PrincipalType
from backend.domain.provision_source import ProvisionSource
from backend.services.signup_abuse_guard import SignupAbuseGuard
from backend.services.tenant_lifecycle import TenantProvisionResult
from backend.services.tenant_onboarding_orchestrator import (
    DuplicateEmailError,
    InvalidVerificationTokenError,
    TenantOnboardingOrchestrator,
    VerificationExpiredError,
)


def _settings(**overrides) -> Settings:
    defaults = {
        "signup_enabled": True,
        "signup_email_limit_per_hour": 3,
        "signup_resend_email_limit_per_hour": 2,
        "signup_verify_failures_per_hour": 10,
        "signup_bootstrap_key_ttl_hours": 72,
        "signup_verification_ttl_hours": 24,
        "signup_expose_verification_token": True,
    }
    defaults.update(overrides)
    return Settings.model_construct(**defaults)


def _make_orchestrator() -> tuple[TenantOnboardingOrchestrator, MagicMock]:
    session = MagicMock()
    orchestrator = TenantOnboardingOrchestrator(session, settings=_settings())
    orchestrator._members = MagicMock()
    orchestrator._tenants = MagicMock()
    orchestrator._lifecycle = MagicMock()
    orchestrator._api_keys = MagicMock()
    orchestrator._abuse_guard = MagicMock(spec=SignupAbuseGuard)
    orchestrator._token_issuer = MagicMock()
    return orchestrator, session


def test_begin_signup_happy_path() -> None:
    orchestrator, session = _make_orchestrator()
    tenant_id = uuid.uuid4()
    orchestrator._members.get_owner_by_email_canonical.return_value = None
    orchestrator._tenants.get_by_slug.return_value = None
    orchestrator._lifecycle.provision.return_value = TenantProvisionResult(
        tenant_id=tenant_id,
        slug="acme",
        plan="free",
        status="active",
        source=ProvisionSource.SELF_SERVE,
    )
    expires_at = datetime.now(UTC) + timedelta(hours=24)
    orchestrator._token_issuer.issue.return_value = MagicMock(
        plaintext="verify-token",
        token_hash="hash",
        expires_at=expires_at,
    )
    member = MagicMock()
    member.id = uuid.uuid4()
    orchestrator._members.create.return_value = member

    receipt = orchestrator.begin_signup(
        org_name="Acme",
        email="owner@example.com",
        slug=None,
        client_ip_hash="ip-hash",
    )

    assert receipt.tenant_id == tenant_id
    assert receipt.status == "pending_verification"
    assert receipt.verification_token_plaintext == "verify-token"
    session.flush.assert_called_once()
    orchestrator._abuse_guard.record_attempt.assert_called()


def test_begin_signup_rejects_duplicate_email() -> None:
    orchestrator, _session = _make_orchestrator()
    orchestrator._members.get_owner_by_email_canonical.side_effect = [
        MagicMock(status="active"),
    ]

    with pytest.raises(DuplicateEmailError):
        orchestrator.begin_signup(
            org_name="Acme",
            email="owner@example.com",
            slug=None,
            client_ip_hash="ip-hash",
        )


def test_complete_verification_issues_bootstrap_key() -> None:
    orchestrator, _session = _make_orchestrator()
    member = MagicMock()
    member.id = uuid.uuid4()
    member.tenant_id = uuid.uuid4()
    member.email_canonical = "owner@example.com"
    member.verification_expires_at = datetime.now(UTC) + timedelta(hours=1)
    member.verification_token_hash = "hash"
    orchestrator._members.list_pending_with_verification_tokens.return_value = [member]
    orchestrator._token_issuer.verify.return_value = True
    orchestrator._api_keys.count_active_keys.return_value = 0
    record = MagicMock(key_id="kid123")
    orchestrator._api_keys.create_key.return_value = ("secret", record)

    with patch("backend.services.tenant_onboarding_orchestrator.QuotaEnforcementService") as quota_cls:
        quota_cls.return_value.check_api_key_limit.return_value = None
        result = orchestrator.complete_verification(token="verify-token", client_ip_hash="ip-hash")

    assert result.key_id == "kid123"
    assert result.api_key == "kid123.secret"
    orchestrator._members.activate_member.assert_called_once()


def test_complete_verification_rejects_expired_token() -> None:
    orchestrator, _session = _make_orchestrator()
    member = MagicMock()
    member.email_canonical = "owner@example.com"
    member.verification_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    orchestrator._members.list_pending_with_verification_tokens.return_value = [member]
    orchestrator._token_issuer.verify.return_value = True

    with pytest.raises(VerificationExpiredError):
        orchestrator.complete_verification(token="verify-token", client_ip_hash="ip-hash")


def test_complete_verification_rejects_invalid_token() -> None:
    orchestrator, _session = _make_orchestrator()
    orchestrator._members.list_pending_with_verification_tokens.return_value = []

    with pytest.raises(InvalidVerificationTokenError):
        orchestrator.complete_verification(token="bad-token", client_ip_hash="ip-hash")


def test_promote_bootstrap_key_revokes_bootstrap() -> None:
    orchestrator, _session = _make_orchestrator()
    tenant_id = uuid.uuid4()
    principal = MachinePrincipal(
        subject_id="machine:bootstrap-key",
        tenant_id=str(tenant_id),
        principal_type=PrincipalType.MACHINE,
        roles=("signup_bootstrap",),
        permissions=frozenset(),
        key_id="bootstrap-key",
    )
    bootstrap_record = MagicMock()
    bootstrap_record.key_id = "bootstrap-key"
    bootstrap_record.purpose = "bootstrap"
    bootstrap_record.revoked = False
    orchestrator._api_keys.count_active_keys.return_value = 1
    operational = MagicMock(key_id="op-key")
    orchestrator._api_keys.create_key.return_value = ("op-secret", operational)

    with (
        patch("backend.services.tenant_onboarding_orchestrator.ApiKeyRepository") as repo_cls,
        patch("backend.services.tenant_onboarding_orchestrator.QuotaEnforcementService") as quota_cls,
    ):
        repo_cls.return_value.get_by_key_id.return_value = bootstrap_record
        quota_cls.return_value.check_api_key_limit.return_value = None
        orchestrator._get_active_owner_for_tenant = MagicMock(return_value=MagicMock())
        result = orchestrator.promote_bootstrap_key(principal=principal)

    assert result.key_id == "op-key"
    assert result.revoked_bootstrap_key_id == "bootstrap-key"
    orchestrator._api_keys.revoke_key.assert_called_once_with(key_id="bootstrap-key")
