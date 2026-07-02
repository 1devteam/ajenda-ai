"""OIDC browser login orchestration for human customer principals."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.auth.id_token_validator import IdTokenValidator
from backend.auth.jwt_validator import JwtValidationError
from backend.auth.member_roles import membership_role_to_rbac
from backend.auth.oidc_discovery import OidcDiscoveryClient
from backend.auth.session_token import SessionTokenService
from backend.domain.audit_event import AuditEvent
from backend.domain.tenant_member import TenantMember
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.customer_auth_session_repository import CustomerAuthSessionRepository
from backend.repositories.oidc_login_intent_repository import OidcLoginIntentRepository
from backend.repositories.tenant_member_repository import TenantMemberRepository
from backend.repositories.tenant_repository import TenantRepository
from backend.services.auth_login_abuse_guard import AuthLoginAbuseGuard, AuthLoginAbuseLimits
from backend.utils.email_canonical import CanonicalEmail, canonicalize_email

logger = logging.getLogger(__name__)


class OidcLoginDisabledError(RuntimeError):
    """Raised when OIDC login is not configured."""


class OidcLoginValidationError(ValueError):
    """Raised for invalid login input."""


class OidcAccountNotFoundError(LookupError):
    """Raised when no active membership matches the authenticated identity."""


class OidcAccountPendingVerificationError(LookupError):
    """Raised when membership exists but email verification is incomplete."""


@dataclass(frozen=True, slots=True)
class OidcTenantChoice:
    tenant_id: str
    org_name: str
    slug: str


class OidcMultipleTenantsError(LookupError):
    """Raised when multiple active memberships require explicit tenant selection."""

    def __init__(self, message: str, *, tenants: tuple[OidcTenantChoice, ...] = ()) -> None:
        super().__init__(message)
        self.tenants = tenants


@dataclass(frozen=True, slots=True)
class OidcStartResult:
    login_intent_id: str
    authorization_url: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class CustomerSessionResult:
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int
    tenant_id: str
    email: str
    org_name: str
    slug: str
    plan: str


@dataclass(frozen=True, slots=True)
class OidcPublicConfig:
    enabled: bool
    provider: str
    client_id: str | None
    authorization_endpoint: str | None
    scopes: str


class OidcLoginService:
    """Server-side OIDC authorization code + PKCE login for customer UI."""

    def __init__(self, session: Session, *, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._intents = OidcLoginIntentRepository(session)
        self._sessions = CustomerAuthSessionRepository(session)
        self._members = TenantMemberRepository(session)
        self._tenants = TenantRepository(session)
        self._audit = AuditEventRepository(session)
        self._abuse = AuthLoginAbuseGuard(
            session,
            limits=AuthLoginAbuseLimits(
                start_ip_per_hour=settings.auth_login_start_ip_limit_per_hour,
                callback_ip_per_hour=settings.auth_login_callback_ip_limit_per_hour,
                callback_email_per_hour=settings.auth_login_callback_email_limit_per_hour,
                refresh_ip_per_hour=settings.auth_login_refresh_ip_limit_per_hour,
            ),
        )

    def public_config(self) -> OidcPublicConfig:
        if not self._settings.oidc_login_ready:
            return OidcPublicConfig(
                enabled=False,
                provider=self._settings.oidc_provider,
                client_id=None,
                authorization_endpoint=None,
                scopes=self._settings.oidc_scopes,
            )
        metadata = self._discovery().get_metadata()
        return OidcPublicConfig(
            enabled=True,
            provider=self._settings.oidc_provider,
            client_id=self._settings.oidc_client_id,
            authorization_endpoint=metadata.authorization_endpoint,
            scopes=self._settings.oidc_scopes,
        )

    def start_login(
        self,
        *,
        redirect_uri: str,
        code_challenge: str,
        client_ip_hash: str,
    ) -> OidcStartResult:
        self._assert_enabled()
        self._validate_redirect_uri(redirect_uri)
        if not code_challenge.strip():
            raise OidcLoginValidationError("code_challenge is required")
        self._validate_code_challenge(code_challenge.strip())

        self._abuse.check_start_ip(client_ip_hash=client_ip_hash)
        now = datetime.now(tz=UTC)
        expires_at = now + timedelta(minutes=self._settings.oidc_login_intent_ttl_minutes)
        nonce = secrets.token_urlsafe(24)
        intent = self._intents.create(
            code_challenge=code_challenge.strip(),
            redirect_uri=redirect_uri.strip(),
            nonce=nonce,
            client_ip_hash=client_ip_hash,
            expires_at=expires_at,
        )
        self._abuse.record(
            client_ip_hash=client_ip_hash,
            route=AuthLoginAbuseGuard.ROUTE_START,
            outcome="accepted",
        )

        metadata = self._discovery().get_metadata()
        params = {
            "client_id": self._settings.oidc_client_id,
            "response_type": "code",
            "scope": self._settings.oidc_scopes,
            "redirect_uri": redirect_uri.strip(),
            "state": str(intent.id),
            "nonce": nonce,
            "code_challenge": code_challenge.strip(),
            "code_challenge_method": "S256",
        }
        authorization_url = f"{metadata.authorization_endpoint}?{urlencode(params)}"
        return OidcStartResult(
            login_intent_id=str(intent.id),
            authorization_url=authorization_url,
            expires_at=expires_at.isoformat(),
        )

    def complete_login(
        self,
        *,
        login_intent_id: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        client_ip_hash: str,
        tenant_id: str | None = None,
    ) -> CustomerSessionResult:
        self._assert_enabled()
        self._abuse.check_callback_ip(client_ip_hash=client_ip_hash)

        if not code.strip() or not code_verifier.strip():
            raise OidcLoginValidationError("authorization code and code_verifier are required")

        try:
            intent_uuid = uuid.UUID(login_intent_id)
        except ValueError as exc:
            raise OidcLoginValidationError("invalid login_intent_id") from exc

        intent = self._intents.get(intent_uuid)
        now = datetime.now(tz=UTC)
        if intent is None or intent.consumed_at is not None or intent.expires_at <= now:
            self._abuse.record(
                client_ip_hash=client_ip_hash,
                route=AuthLoginAbuseGuard.ROUTE_CALLBACK,
                outcome="invalid_input",
            )
            raise OidcLoginValidationError("login intent is invalid or expired")
        if intent.redirect_uri != redirect_uri.strip():
            raise OidcLoginValidationError("redirect_uri mismatch")
        if intent.client_ip_hash != client_ip_hash:
            raise OidcLoginValidationError("login intent client mismatch")
        if not self._verify_pkce(code_verifier=code_verifier.strip(), code_challenge=intent.code_challenge):
            raise OidcLoginValidationError("invalid PKCE code_verifier")

        token_payload = self._exchange_code(
            code=code.strip(),
            redirect_uri=redirect_uri.strip(),
            code_verifier=code_verifier.strip(),
        )
        id_token = token_payload.get("id_token")
        if not isinstance(id_token, str) or not id_token.strip():
            raise OidcLoginValidationError("identity provider did not return an id_token")

        provider_access_token = token_payload.get("access_token")
        if not isinstance(provider_access_token, str) or not provider_access_token.strip():
            provider_access_token = None

        try:
            claims = self._id_token_validator().validate(
                id_token,
                expected_nonce=intent.nonce,
                access_token=provider_access_token,
            )
        except JwtValidationError as exc:
            raise OidcLoginValidationError("identity provider token validation failed") from exc
        canonical = canonicalize_email(claims.email)
        self._abuse.check_callback_email(email_canonical=canonical.canonical)
        member = self._resolve_member(
            external_subject_id=claims.sub,
            email=canonical,
            tenant_id=tenant_id,
        )

        if member.external_subject_id is None:
            self._members.link_external_subject(member, external_subject_id=claims.sub)
        elif member.external_subject_id != claims.sub:
            self._abuse.record(
                client_ip_hash=client_ip_hash,
                route=AuthLoginAbuseGuard.ROUTE_CALLBACK,
                outcome="error",
                email_canonical=canonical.canonical,
            )
            raise OidcLoginValidationError("identity provider subject does not match linked membership")

        tenant = self._tenants.get(member.tenant_id)
        if tenant is None or tenant.is_deleted() or tenant.is_suspended():
            raise OidcAccountNotFoundError("tenant is not available for login")

        session_tokens = self._issue_session(
            member=member,
            email=canonical.raw,
            client_ip_hash=client_ip_hash,
        )
        self._intents.consume(intent, consumed_at=now)
        self._abuse.record(
            client_ip_hash=client_ip_hash,
            route=AuthLoginAbuseGuard.ROUTE_CALLBACK,
            outcome="accepted",
            email_canonical=canonical.canonical,
        )
        self._audit.append(
            AuditEvent(
                tenant_id=str(member.tenant_id),
                mission_id=None,
                category="auth",
                action="customer_oidc_login",
                actor=claims.sub,
                details=f"OIDC login for member {member.id}",
                payload_json={"member_id": str(member.id), "provider": self._settings.oidc_provider},
            )
        )
        return CustomerSessionResult(
            access_token=session_tokens.access_token,
            refresh_token=session_tokens.refresh_token,
            expires_in=session_tokens.expires_in,
            refresh_expires_in=session_tokens.refresh_expires_in,
            tenant_id=str(member.tenant_id),
            email=canonical.raw,
            org_name=tenant.name,
            slug=tenant.slug,
            plan=tenant.plan,
        )

    def refresh_session(self, *, refresh_token: str, client_ip_hash: str) -> CustomerSessionResult:
        self._assert_enabled()
        self._abuse.check_refresh_ip(client_ip_hash=client_ip_hash)
        if not refresh_token.strip():
            raise OidcLoginValidationError("refresh_token is required")

        refresh_hash = self._hash_refresh_token(refresh_token.strip())
        record = self._sessions.get_by_refresh_token_hash(refresh_hash)
        now = datetime.now(tz=UTC)
        if record is None or record.revoked_at is not None or record.refresh_expires_at <= now:
            raise OidcLoginValidationError("refresh token is invalid or expired")

        member = self._members.get(record.member_id)
        if member is None or not member.is_active():
            raise OidcAccountNotFoundError("membership is no longer active")

        tenant = self._tenants.get(record.tenant_id)
        if tenant is None or tenant.is_deleted() or tenant.is_suspended():
            raise OidcAccountNotFoundError("tenant is not available for login")

        self._sessions.revoke(record, revoked_at=now)
        session_tokens = self._issue_session(
            member=member,
            email=member.email_raw,
            client_ip_hash=client_ip_hash,
        )
        self._abuse.record(
            client_ip_hash=client_ip_hash,
            route=AuthLoginAbuseGuard.ROUTE_REFRESH,
            outcome="accepted",
            email_canonical=member.email_canonical,
        )
        return CustomerSessionResult(
            access_token=session_tokens.access_token,
            refresh_token=session_tokens.refresh_token,
            expires_in=session_tokens.expires_in,
            refresh_expires_in=session_tokens.refresh_expires_in,
            tenant_id=str(member.tenant_id),
            email=member.email_raw,
            org_name=tenant.name,
            slug=tenant.slug,
            plan=tenant.plan,
        )

    def revoke_session(self, *, access_jti: str) -> None:
        """Revoke the full customer session, invalidating access and refresh tokens."""
        record = self._sessions.get_by_access_jti(access_jti)
        if record is None or record.revoked_at is not None:
            return
        self._sessions.revoke(record)

    def revoke_access_token(self, *, access_jti: str) -> None:
        self.revoke_session(access_jti=access_jti)

    def _issue_session(
        self,
        *,
        member: TenantMember,
        email: str,
        client_ip_hash: str,
    ) -> CustomerSessionResult:
        token_service = self._session_token_service()
        access_jti = secrets.token_hex(16)
        refresh_token = secrets.token_urlsafe(48)
        refresh_hash = self._hash_refresh_token(refresh_token)
        now = datetime.now(tz=UTC)
        access_expires = now + timedelta(seconds=self._settings.session_access_ttl_seconds)
        refresh_expires = now + timedelta(seconds=self._settings.session_refresh_ttl_seconds)
        rbac_role = membership_role_to_rbac(member.role)
        access_token, _ = token_service.issue_access_token(
            member_id=member.id,
            tenant_id=member.tenant_id,
            email=email,
            roles=(rbac_role,),
            jti=access_jti,
        )
        self._sessions.create(
            member_id=member.id,
            tenant_id=member.tenant_id,
            access_jti=access_jti,
            refresh_token_hash=refresh_hash,
            expires_at=access_expires,
            refresh_expires_at=refresh_expires,
            client_ip_hash=client_ip_hash,
        )
        return CustomerSessionResult(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._settings.session_access_ttl_seconds,
            refresh_expires_in=self._settings.session_refresh_ttl_seconds,
            tenant_id=str(member.tenant_id),
            email=email,
            org_name="",
            slug="",
            plan="",
        )

    def _resolve_member(
        self,
        *,
        external_subject_id: str,
        email: CanonicalEmail,
        tenant_id: str | None,
    ) -> TenantMember:
        linked = self._members.get_active_by_external_subject_id(external_subject_id)
        if linked is not None:
            return linked

        active_members = self._members.list_active_for_email(email.canonical)
        if tenant_id:
            try:
                tenant_uuid = uuid.UUID(tenant_id)
            except ValueError as exc:
                raise OidcLoginValidationError("invalid tenant_id") from exc
            for member in active_members:
                if member.tenant_id == tenant_uuid:
                    return member
            raise OidcAccountNotFoundError("no active membership for tenant")

        if len(active_members) == 1:
            return active_members[0]
        if len(active_members) > 1:
            choices = self._tenant_choices_for_members(active_members)
            raise OidcMultipleTenantsError(
                "multiple active workspaces for this email",
                tenants=choices,
            )

        pending = self._members.get_owner_by_email_canonical(
            email.canonical,
            statuses=frozenset({"pending_verification"}),
        )
        if pending is not None:
            raise OidcAccountPendingVerificationError("email verification is required before sign-in")

        raise OidcAccountNotFoundError("no account found for this identity")

    def _exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str) -> dict[str, Any]:
        metadata = self._discovery().get_metadata()
        data = {
            "grant_type": "authorization_code",
            "client_id": self._settings.oidc_client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
        if self._settings.oidc_client_secret:
            data["client_secret"] = self._settings.oidc_client_secret

        try:
            response = httpx.post(
                metadata.token_endpoint,
                data=data,
                headers={"Accept": "application/json"},
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning("oidc_token_exchange_failed", extra={"error": str(exc)})
            raise OidcLoginValidationError("identity provider token exchange failed") from exc

        if not isinstance(payload, dict):
            raise OidcLoginValidationError("identity provider returned an invalid token response")
        return payload

    def _verify_pkce(self, *, code_verifier: str, code_challenge: str) -> bool:
        digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        import base64

        computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return secrets.compare_digest(computed, code_challenge)

    def _validate_redirect_uri(self, redirect_uri: str) -> None:
        normalized = redirect_uri.strip()
        if not normalized:
            raise OidcLoginValidationError("redirect_uri is required")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"}:
            raise OidcLoginValidationError("redirect_uri must use http or https")
        if not parsed.netloc:
            raise OidcLoginValidationError("redirect_uri must include a host")
        if parsed.fragment:
            raise OidcLoginValidationError("redirect_uri must not include a fragment")
        if self._settings.env == "production" and parsed.scheme != "https":
            raise OidcLoginValidationError("redirect_uri must use https in production")
        allowed = self._settings.oidc_redirect_uri_allowlist_set
        if allowed and normalized not in allowed:
            raise OidcLoginValidationError("redirect_uri is not allowed")

    @staticmethod
    def _validate_code_challenge(code_challenge: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9\-._~]{43,128}", code_challenge):
            raise OidcLoginValidationError("code_challenge must be a base64url-encoded SHA-256 digest")

    def _tenant_choices_for_members(self, members: list[TenantMember]) -> tuple[OidcTenantChoice, ...]:
        choices: list[OidcTenantChoice] = []
        for member in members:
            tenant = self._tenants.get(member.tenant_id)
            if tenant is None or tenant.is_deleted() or tenant.is_suspended():
                continue
            choices.append(
                OidcTenantChoice(
                    tenant_id=str(member.tenant_id),
                    org_name=tenant.name,
                    slug=tenant.slug,
                )
            )
        return tuple(choices)

    def _assert_enabled(self) -> None:
        if not self._settings.oidc_login_enabled:
            raise OidcLoginDisabledError("OIDC login is not enabled")

    def _discovery(self) -> OidcDiscoveryClient:
        return OidcDiscoveryClient(issuer=self._settings.oidc_issuer)

    def _id_token_validator(self) -> IdTokenValidator:
        audience = self._settings.oidc_id_token_audience or self._settings.oidc_client_id
        metadata = self._discovery().get_metadata()
        return IdTokenValidator(
            jwks_uri=metadata.jwks_uri,
            issuer=metadata.issuer,
            audience=audience,
        )

    def _session_token_service(self) -> SessionTokenService:
        return SessionTokenService(
            signing_secret=self._settings.session_signing_secret,
            access_ttl_seconds=self._settings.session_access_ttl_seconds,
        )

    @staticmethod
    def _hash_refresh_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def validate_customer_access_token(
        *,
        settings: Settings,
        token: str,
        session: Session,
    ) -> tuple[str, str, str, tuple[str, ...]]:
        """Validate Ajenda access token and ensure backing session is active."""
        service = SessionTokenService(
            signing_secret=settings.session_signing_secret,
            access_ttl_seconds=settings.session_access_ttl_seconds,
        )
        try:
            claims = service.validate_access_token(token)
        except JwtValidationError as exc:
            raise JwtValidationError(str(exc)) from exc

        record = CustomerAuthSessionRepository(session).get_by_access_jti(claims.jti)
        now = datetime.now(tz=UTC)
        if record is None or record.revoked_at is not None or record.expires_at <= now:
            raise JwtValidationError("session has been revoked or expired")
        return claims.member_id, claims.tenant_id, claims.email, claims.roles
