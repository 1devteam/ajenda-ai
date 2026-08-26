"""Tenant onboarding orchestrator — signup, verify, resend, and promote flows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.auth.principal import MachinePrincipal
from backend.db.tenant_session import activate_tenant_session
from backend.domain.governance_event import GovernanceEvent
from backend.domain.provision_source import ProvisionSource
from backend.domain.tenant_member import TenantMember
from backend.repositories.api_key_repository import ApiKeyRepository
from backend.repositories.tenant_member_repository import TenantMemberRepository
from backend.repositories.tenant_repository import TenantRepository
from backend.services.api_key_service import ApiKeyService
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError
from backend.services.signup_abuse_guard import SignupAbuseGuard, SignupAbuseLimits
from backend.services.tenant_lifecycle import TenantLifecycleService
from backend.services.verification_token import VerificationTokenIssuer
from backend.utils.email_canonical import CanonicalEmail, InvalidEmailError, canonicalize_email
from backend.utils.slug import allocate_slug


class DuplicateEmailError(ValueError):
    """Raised when a canonical owner email already exists."""


class VerificationPendingError(DuplicateEmailError):
    """Raised when a pending verification already exists for the email."""


class InvalidVerificationTokenError(ValueError):
    """Raised when a verification code is invalid."""


class VerificationExpiredError(ValueError):
    """Raised when a verification code has expired."""


class MemberNotFoundError(ValueError):
    """Raised when a membership row cannot be found."""


class BootstrapPromotionError(ValueError):
    """Raised when bootstrap promotion preconditions fail."""


@dataclass(frozen=True, slots=True)
class SignupReceipt:
    tenant_id: uuid.UUID
    slug: str
    plan: str
    email: CanonicalEmail
    status: str
    verification_expires_at: datetime
    verification_token_plaintext: str
    member_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class VerificationResult:
    tenant_id: uuid.UUID
    key_id: str
    api_key: str
    bootstrap_expires_at: datetime


@dataclass(frozen=True, slots=True)
class ResendVerificationResult:
    tenant_id: uuid.UUID
    email: CanonicalEmail
    verification_expires_at: datetime
    verification_token_plaintext: str
    member_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class PromoteBootstrapResult:
    tenant_id: uuid.UUID
    key_id: str
    api_key: str
    revoked_bootstrap_key_id: str


class TenantOnboardingOrchestrator:
    """Coordinates self-serve signup workflows without owning transactions."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._members = TenantMemberRepository(session)
        self._tenants = TenantRepository(session)
        self._lifecycle = TenantLifecycleService(session)
        self._api_keys = ApiKeyService(session)
        self._abuse_guard = SignupAbuseGuard(
            session,
            limits=SignupAbuseLimits(
                signup_email_per_hour=self._settings.signup_email_limit_per_hour,
                resend_email_per_hour=self._settings.signup_resend_email_limit_per_hour,
                verify_failures_per_hour=self._settings.signup_verify_failures_per_hour,
            ),
            signup_enabled=self._settings.signup_enabled,
        )
        self._token_issuer = VerificationTokenIssuer(ttl_hours=self._settings.signup_verification_ttl_hours)

    def begin_signup(
        self,
        *,
        org_name: str,
        email: str,
        slug: str | None,
        client_ip_hash: str,
        password: str | None = None,
    ) -> SignupReceipt:
        """Create a pending membership; password possession never verifies email ownership."""
        self._abuse_guard.assert_signup_enabled()

        try:
            canonical = canonicalize_email(email)
        except InvalidEmailError as exc:
            self._abuse_guard.record_attempt(
                email_canonical=None,
                client_ip_hash=client_ip_hash,
                route=SignupAbuseGuard.ROUTE_SIGNUP,
                outcome="invalid_input",
            )
            raise ValueError(str(exc)) from exc

        self._abuse_guard.check_signup_email(email_canonical=canonical.canonical)
        self._assert_email_available(canonical.canonical)

        allocated_slug = allocate_slug(self._tenants, org_name=org_name, client_slug=slug)
        provisioned = self._lifecycle.provision(
            name=org_name,
            slug=allocated_slug,
            plan="free",
            actor=f"signup:{canonical.canonical}",
            source=ProvisionSource.SELF_SERVE,
        )

        issued = self._token_issuer.issue()
        password_hash = PasswordHasher().hash(password) if password else None
        member = self._members.create(
            tenant_id=provisioned.tenant_id,
            email_raw=canonical.raw,
            email_canonical=canonical.canonical,
            verification_token_hash=issued.token_hash,
            verification_expires_at=issued.expires_at,
            verification_delivery_status="pending",
            password_hash=password_hash,
        )
        self._session.flush()

        self._abuse_guard.record_attempt(
            email_canonical=canonical.canonical,
            client_ip_hash=client_ip_hash,
            route=SignupAbuseGuard.ROUTE_SIGNUP,
            outcome="accepted",
        )

        return SignupReceipt(
            tenant_id=provisioned.tenant_id,
            slug=provisioned.slug,
            plan=provisioned.plan,
            email=canonical,
            status="pending_verification",
            verification_expires_at=issued.expires_at,
            verification_token_plaintext=issued.plaintext,
            member_id=member.id,
        )

    def complete_verification(
        self,
        *,
        email: str,
        code: str,
        client_ip_hash: str,
    ) -> VerificationResult:
        """Verify one pending email/code pair and activate that membership."""
        try:
            canonical = canonicalize_email(email)
        except InvalidEmailError as exc:
            self._abuse_guard.record_attempt(
                email_canonical=None,
                client_ip_hash=client_ip_hash,
                route=SignupAbuseGuard.ROUTE_VERIFY,
                outcome="invalid_input",
            )
            raise InvalidVerificationTokenError("invalid verification code") from exc

        member = self._members.get_pending_owner_by_email_for_update(canonical.canonical)
        if member is None or member.verification_token_hash is None:
            self._abuse_guard.record_attempt(
                email_canonical=canonical.canonical,
                client_ip_hash=client_ip_hash,
                route=SignupAbuseGuard.ROUTE_VERIFY,
                outcome="invalid_input",
            )
            raise InvalidVerificationTokenError("invalid verification code")

        now = datetime.now(UTC)
        self._abuse_guard.check_verify_failures(email_canonical=member.email_canonical, now=now)

        if not self._token_issuer.verify(
            plaintext=code,
            token_hash=member.verification_token_hash,
        ):
            self._abuse_guard.record_attempt(
                email_canonical=member.email_canonical,
                client_ip_hash=client_ip_hash,
                route=SignupAbuseGuard.ROUTE_VERIFY,
                outcome="invalid_input",
            )
            raise InvalidVerificationTokenError("invalid verification code")

        if member.verification_expires_at is not None and now >= member.verification_expires_at:
            self._abuse_guard.record_attempt(
                email_canonical=member.email_canonical,
                client_ip_hash=client_ip_hash,
                route=SignupAbuseGuard.ROUTE_VERIFY,
                outcome="invalid_input",
            )
            raise VerificationExpiredError("verification code expired")

        self._members.activate_member(member, verified_at=now)

        activate_tenant_session(self._session, str(member.tenant_id))
        try:
            QuotaEnforcementService(self._session).reserve_api_key_capacity(member.tenant_id)
        except QuotaExceededError:
            self._abuse_guard.record_attempt(
                email_canonical=member.email_canonical,
                client_ip_hash=client_ip_hash,
                route=SignupAbuseGuard.ROUTE_VERIFY,
                outcome="error",
            )
            raise

        bootstrap_expires_at = now + timedelta(hours=self._settings.signup_bootstrap_key_ttl_hours)
        plaintext, record = self._api_keys.create_key(
            tenant_id=str(member.tenant_id),
            roles=("signup_bootstrap",),
            purpose="bootstrap",
            expires_at=bootstrap_expires_at,
        )
        self._emit_governance_event(
            tenant_id=member.tenant_id,
            event_type="tenant_owner_verified",
            actor=f"signup:{member.email_canonical}",
            decision="Tenant owner email verified and bootstrap key issued",
            payload={"member_id": str(member.id)},
        )
        self._abuse_guard.record_attempt(
            email_canonical=member.email_canonical,
            client_ip_hash=client_ip_hash,
            route=SignupAbuseGuard.ROUTE_VERIFY,
            outcome="accepted",
        )
        return VerificationResult(
            tenant_id=member.tenant_id,
            key_id=record.key_id,
            api_key=f"{record.key_id}.{plaintext}",
            bootstrap_expires_at=bootstrap_expires_at,
        )

    def resend_verification(self, *, email: str, client_ip_hash: str) -> ResendVerificationResult:
        self._abuse_guard.assert_signup_enabled()
        canonical = canonicalize_email(email)
        self._abuse_guard.check_resend_email(email_canonical=canonical.canonical)

        member = self._members.get_pending_owner_by_email_for_update(canonical.canonical)
        if member is None:
            raise MemberNotFoundError("no pending verification found for this email")

        now = datetime.now(UTC)
        issued = self._token_issuer.issue(now=now)
        self._members.update_verification_token(
            member,
            token_hash=issued.token_hash,
            expires_at=issued.expires_at,
            delivery_status="pending",
        )

        self._abuse_guard.record_attempt(
            email_canonical=canonical.canonical,
            client_ip_hash=client_ip_hash,
            route=SignupAbuseGuard.ROUTE_RESEND,
            outcome="accepted",
        )
        return ResendVerificationResult(
            tenant_id=member.tenant_id,
            email=canonical,
            verification_expires_at=issued.expires_at,
            verification_token_plaintext=issued.plaintext,
            member_id=member.id,
        )

    def promote_bootstrap_key(self, *, principal: MachinePrincipal) -> PromoteBootstrapResult:
        if principal.key_id is None:
            raise BootstrapPromotionError("bootstrap key promotion requires an API key principal")

        key_repo = ApiKeyRepository(self._session)
        bootstrap_record = key_repo.get_by_key_id_for_update(principal.key_id)
        if bootstrap_record is None:
            raise BootstrapPromotionError("bootstrap key not found")
        if bootstrap_record.purpose != "bootstrap":
            raise BootstrapPromotionError("only bootstrap keys may be promoted through this path")
        if bootstrap_record.revoked:
            raise BootstrapPromotionError("bootstrap key is revoked")

        tenant_id = uuid.UUID(str(principal.tenant_id))
        active_owner = self._get_active_owner_for_tenant(tenant_id)
        if active_owner is None:
            raise BootstrapPromotionError("tenant owner membership is not active")

        activate_tenant_session(self._session, str(tenant_id))
        QuotaEnforcementService(self._session).reserve_api_key_capacity(
            tenant_id,
            replacing_active_keys=1,
        )

        plaintext, record = self._api_keys.create_key(
            tenant_id=str(tenant_id),
            roles=("tenant_operator",),
            purpose="operational",
        )
        self._api_keys.revoke_key(key_id=bootstrap_record.key_id)
        self._emit_governance_event(
            tenant_id=tenant_id,
            event_type="bootstrap_key_promoted",
            actor=f"machine:{bootstrap_record.key_id}",
            decision="Bootstrap API key promoted to tenant_operator key",
            payload={
                "revoked_bootstrap_key_id": bootstrap_record.key_id,
                "operational_key_id": record.key_id,
            },
        )
        return PromoteBootstrapResult(
            tenant_id=tenant_id,
            key_id=record.key_id,
            api_key=f"{record.key_id}.{plaintext}",
            revoked_bootstrap_key_id=bootstrap_record.key_id,
        )

    def mark_delivery_failed(self, *, member_id: uuid.UUID) -> None:
        member = self._members.mark_verification_delivery_failed(member_id)
        if member is None:
            return
        self._abuse_guard.record_attempt(
            email_canonical=member.email_canonical,
            client_ip_hash="delivery-failure",
            route=SignupAbuseGuard.ROUTE_SIGNUP,
            outcome="delivery_failed",
        )

    def _assert_email_available(self, email_canonical: str) -> None:
        active = self._members.get_owner_by_email_canonical(
            email_canonical,
            statuses=frozenset({"active"}),
        )
        if active is not None:
            self._abuse_guard.record_attempt(
                email_canonical=email_canonical,
                client_ip_hash="duplicate",
                route=SignupAbuseGuard.ROUTE_SIGNUP,
                outcome="duplicate_email",
            )
            raise DuplicateEmailError("An account with this email already exists.")

        pending = self._members.get_owner_by_email_canonical(
            email_canonical,
            statuses=frozenset({"pending_verification"}),
        )
        if pending is not None:
            now = datetime.now(UTC)
            if pending.verification_expires_at is None or now < pending.verification_expires_at:
                self._abuse_guard.record_attempt(
                    email_canonical=email_canonical,
                    client_ip_hash="duplicate",
                    route=SignupAbuseGuard.ROUTE_SIGNUP,
                    outcome="duplicate_email",
                )
                raise VerificationPendingError("A verification is already pending for this email.")

    def _get_active_owner_for_tenant(self, tenant_id: uuid.UUID) -> TenantMember | None:
        from sqlalchemy import select

        stmt = (
            select(TenantMember)
            .where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.role == "tenant_owner",
                TenantMember.status == "active",
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def _emit_governance_event(
        self,
        *,
        tenant_id: uuid.UUID,
        event_type: str,
        actor: str,
        decision: str,
        payload: dict[str, object],
    ) -> None:
        activate_tenant_session(self._session, str(tenant_id))
        event = GovernanceEvent(
            id=uuid.uuid4(),
            tenant_id=str(tenant_id),
            event_type=event_type,
            actor=actor,
            decision=decision,
            payload_json=payload,
            created_at=datetime.now(UTC),
        )
        self._session.add(event)
