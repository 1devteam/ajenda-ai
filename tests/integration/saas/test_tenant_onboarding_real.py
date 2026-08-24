"""Integration tests: self-serve onboarding flow."""

from __future__ import annotations

import uuid

import pytest

from backend.app.config import Settings
from backend.auth.permissions import Permission
from backend.db.tenant_session import activate_tenant_session
from backend.services.api_key_service import ApiKeyService
from backend.services.tenant_onboarding_orchestrator import TenantOnboardingOrchestrator

pytestmark = pytest.mark.integration


def _settings() -> Settings:
    return Settings.model_construct(
        env="test",
        signup_enabled=True,
        signup_expose_verification_token=True,
        signup_email_limit_per_hour=10,
        signup_resend_email_limit_per_hour=10,
        signup_verify_failures_per_hour=20,
        signup_bootstrap_key_ttl_hours=72,
        signup_verification_ttl_hours=24,
        email_provider="noop",
    )


class TestTenantOnboardingReal:
    def test_signup_verify_authenticate_bootstrap_permissions(self, pg_session) -> None:
        email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        orchestrator = TenantOnboardingOrchestrator(pg_session, settings=_settings())

        receipt = orchestrator.begin_signup(
            org_name="Onboarding Co",
            email=email,
            slug=None,
            client_ip_hash="test-ip-hash",
        )
        pg_session.commit()

        verification = orchestrator.complete_verification(
            email=receipt.email.canonical,
            code=receipt.verification_token_plaintext,
            client_ip_hash="test-ip-hash",
        )
        pg_session.commit()

        key_id, plaintext = verification.api_key.split(".", 1)
        activate_tenant_session(pg_session, str(verification.tenant_id))
        principal = ApiKeyService(pg_session).authenticate_machine(
            tenant_id=str(verification.tenant_id),
            key_id=key_id,
            plaintext=plaintext,
        )
        assert principal is not None
        assert Permission.MISSION_CREATE in principal.permissions
        assert Permission.API_KEYS_CREATE not in principal.permissions
        assert principal.roles == ("signup_bootstrap",)

    def test_promote_bootstrap_key_issues_operational_key(self, pg_session) -> None:
        email = f"promote-{uuid.uuid4().hex[:8]}@example.com"
        orchestrator = TenantOnboardingOrchestrator(pg_session, settings=_settings())

        receipt = orchestrator.begin_signup(
            org_name="Promote Co",
            email=email,
            slug=None,
            client_ip_hash="test-ip-hash",
        )
        pg_session.commit()

        verification = orchestrator.complete_verification(
            email=receipt.email.canonical,
            code=receipt.verification_token_plaintext,
            client_ip_hash="test-ip-hash",
        )
        pg_session.commit()

        key_id, plaintext = verification.api_key.split(".", 1)
        api_key_service = ApiKeyService(pg_session)
        activate_tenant_session(pg_session, str(verification.tenant_id))
        bootstrap_principal = api_key_service.authenticate_machine(
            tenant_id=str(verification.tenant_id),
            key_id=key_id,
            plaintext=plaintext,
        )
        assert bootstrap_principal is not None

        promoted = orchestrator.promote_bootstrap_key(principal=bootstrap_principal)
        pg_session.commit()

        assert promoted.revoked_bootstrap_key_id == key_id
        op_key_id, op_plaintext = promoted.api_key.split(".", 1)
        operational = api_key_service.authenticate_machine(
            tenant_id=str(verification.tenant_id),
            key_id=op_key_id,
            plaintext=op_plaintext,
        )
        assert operational is not None
        assert Permission.API_KEYS_CREATE in operational.permissions

        revoked_bootstrap = api_key_service.authenticate_machine(
            tenant_id=str(verification.tenant_id),
            key_id=key_id,
            plaintext=plaintext,
        )
        assert revoked_bootstrap is None
