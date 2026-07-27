from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.domain.audit_event import AuditEvent
from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.provider_runtime_credential_repository import ProviderRuntimeCredentialRepository
from backend.services.credentials.platform_master import platform_master_ready_for
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector

PLATFORM_MASTER_CREDENTIAL_TYPE = "platform_master"
TENANT_API_KEY_CREDENTIAL_TYPE = "api_key"
PLATFORM_MASTER_SENTINEL = "__AJENDA_PLATFORM_MASTER__"

HUBSPOT_EXTERNAL_CRM_ACTIONS = (
    "sales.research",
    "crm.research",
    "crm.read",
    "gtm.crm_upsert",
)
HUBSPOT_EXTERNAL_CRM_SIDE_EFFECTS = ("external_read", "external_write")
GMAIL_EMAIL_ACTIONS = ("gtm.email_send", "gtm.email_check")
GMAIL_EMAIL_SIDE_EFFECTS = ("external_send", "external_read")
SMTP_EMAIL_ACTIONS = ("gtm.email_send",)
SMTP_EMAIL_SIDE_EFFECTS = ("external_send",)
LINKEDIN_READ_ACTIONS = ("linkedin.profile_read", "provider.external_read")
LINKEDIN_READ_SIDE_EFFECTS = ("external_read",)
LINKEDIN_TRUSTED_HOSTS = ("api.linkedin.com",)
SALESFORCE_READ_ACTIONS = ("salesforce.soql_read", "provider.external_read")
SALESFORCE_READ_SIDE_EFFECTS = ("external_read",)
GOOGLE_CALENDAR_READ_ACTIONS = ("google_calendar.events_read", "provider.external_read")
GOOGLE_CALENDAR_READ_SIDE_EFFECTS = ("external_read",)
GOOGLE_CALENDAR_TRUSTED_HOSTS = ("www.googleapis.com",)
GOOGLE_CONTACTS_READ_ACTIONS = ("provider.external_read",)
GOOGLE_CONTACTS_READ_SIDE_EFFECTS = ("external_read",)
GOOGLE_CONTACTS_TRUSTED_HOSTS = ("people.googleapis.com", "www.googleapis.com")
GITHUB_READ_ACTIONS = ("github.repo_read", "provider.external_read")
GITHUB_READ_SIDE_EFFECTS = ("external_read",)
GITHUB_TRUSTED_HOSTS = ("api.github.com",)


class ProviderCredentialManagementError(ValueError):
    """Deterministic management-layer validation failure."""


@dataclass(slots=True)
class ProviderCredentialSummary:
    credential_id: str
    tenant_id: str
    provider: str
    credential_type: str
    enabled: bool
    revoked: bool
    allowed_actions: list[str]
    allowed_side_effect_classes: list[str]
    trusted_destination_hosts: list[str]
    uses_platform_master_key: bool
    platform_master_warning: str | None
    created_at: str
    updated_at: str


@dataclass(slots=True)
class ProviderCredentialCreateResult:
    summary: ProviderCredentialSummary
    secret_returned_once: bool
    warning: str | None = None


class ProviderCredentialManagementService:
    def __init__(self, session: Session, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = ProviderRuntimeCredentialRepository(session)
        self._audit = AuditEventRepository(session)
        self._protector = RuntimeCredentialSecretProtector()

    def register(
        self,
        *,
        tenant_id: str,
        credential_id: str,
        provider: str,
        integration: Literal[
            "hubspot",
            "gmail",
            "smtp",
            "linkedin",
            "salesforce",
            "google_calendar",
            "google_contacts",
            "github",
            "generic",
        ] = "hubspot",
        secret_value: str | None = None,
        use_platform_master_key: bool = False,
        allowed_actions: list[str] | None = None,
        allowed_side_effect_classes: list[str] | None = None,
        trusted_destination_hosts: list[str] | None = None,
        actor_id: str,
    ) -> ProviderCredentialCreateResult:
        normalized_id = _normalize_credential_id(credential_id)
        normalized_provider = provider.strip().lower()
        if normalized_provider not in {"external_crm", "external_read_provider", "external_email"}:
            raise ProviderCredentialManagementError(
                "provider must be external_crm, external_read_provider, or external_email"
            )

        warning: str | None = None
        credential_type = self._resolve_credential_type(
            provider=normalized_provider,
            integration=integration,
            use_platform_master_key=use_platform_master_key,
        )
        ciphertext: str
        normalized_secret: str | None = None

        if use_platform_master_key:
            if not platform_master_ready_for(
                provider=normalized_provider,
                integration=integration,
                settings=self._settings,
            ):
                raise ProviderCredentialManagementError("platform master key mode is not configured on this deployment")
            credential_type = PLATFORM_MASTER_CREDENTIAL_TYPE
            ciphertext = self._protector.encrypt_secret(PLATFORM_MASTER_SENTINEL)
            if normalized_provider == "external_email":
                warning = (
                    "WARNING: This credential uses the platform master email SMTP lane. "
                    "All tenants sharing this mode depend on operator SMTP rotation and "
                    "centralized blast-radius risk. Prefer per-tenant email credentials for production."
                )
            else:
                warning = (
                    "WARNING: This credential uses the platform master HubSpot key. "
                    "All tenants sharing this mode depend on operator key rotation and "
                    "centralized blast-radius risk. Prefer per-tenant keys for production."
                )
        else:
            if not secret_value or not secret_value.strip():
                raise ProviderCredentialManagementError("secret_value is required unless use_platform_master_key=true")
            normalized_secret = secret_value.strip()
            if credential_type == "smtp":
                self._validate_smtp_secret(normalized_secret)
            ciphertext = self._protector.encrypt_secret(normalized_secret)

        actions, side_effects, hosts = self._default_scope(
            provider=normalized_provider,
            integration=integration,
            secret_value=normalized_secret,
            allowed_actions=allowed_actions,
            allowed_side_effect_classes=allowed_side_effect_classes,
            trusted_destination_hosts=trusted_destination_hosts,
        )

        record = ProviderRuntimeCredential(
            id=f"prc-{uuid.uuid4()}",
            tenant_id=tenant_id,
            credential_id=normalized_id,
            provider=normalized_provider,
            credential_type=credential_type,
            enabled=True,
            revoked=False,
            deleted=False,
            allowed_actions=list(actions),
            allowed_side_effect_classes=list(side_effects),
            trusted_destination_hosts=list(hosts),
            secret_ciphertext=ciphertext,
        )
        saved = self._repo.upsert(record)
        self._emit_audit(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="provider_credential_registered",
            details=f"Registered provider credential {normalized_id} ({normalized_provider})",
            payload={
                "credential_id": normalized_id,
                "provider": normalized_provider,
                "credential_type": credential_type,
                "uses_platform_master_key": use_platform_master_key,
                "trusted_destination_hosts": hosts,
                "warning": warning,
            },
        )
        summary = self._to_summary(saved)
        return ProviderCredentialCreateResult(
            summary=summary,
            secret_returned_once=False,
            warning=warning,
        )

    def list_credentials(self, *, tenant_id: str) -> list[ProviderCredentialSummary]:
        return [self._to_summary(row) for row in self._repo.list_for_tenant(tenant_id=tenant_id)]

    def revoke(self, *, tenant_id: str, credential_id: str, actor_id: str) -> ProviderCredentialSummary:
        normalized_id = _normalize_credential_id(credential_id)
        saved = self._repo.mark_revoked(tenant_id=tenant_id, credential_id=normalized_id)
        self._emit_audit(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="provider_credential_revoked",
            details=f"Revoked provider credential {normalized_id}",
            payload={"credential_id": normalized_id},
        )
        return self._to_summary(saved)

    def delete(self, *, tenant_id: str, credential_id: str, actor_id: str) -> ProviderCredentialSummary:
        normalized_id = _normalize_credential_id(credential_id)
        saved = self._repo.mark_deleted(tenant_id=tenant_id, credential_id=normalized_id)
        self._emit_audit(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="provider_credential_deleted",
            details=f"Deleted provider credential {normalized_id}",
            payload={"credential_id": normalized_id},
        )
        return self._to_summary(saved)

    def _default_scope(
        self,
        *,
        provider: str,
        integration: str,
        secret_value: str | None = None,
        allowed_actions: list[str] | None,
        allowed_side_effect_classes: list[str] | None,
        trusted_destination_hosts: list[str] | None,
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        if provider == "external_crm" and integration == "hubspot":
            actions = tuple(allowed_actions or HUBSPOT_EXTERNAL_CRM_ACTIONS)
            side_effects = tuple(allowed_side_effect_classes or HUBSPOT_EXTERNAL_CRM_SIDE_EFFECTS)
            hosts = tuple(
                trusted_destination_hosts
                or (self._settings.hubspot_crm_adapter_public_host.strip().lower().rstrip("."),)
            )
            return actions, side_effects, hosts
        if provider == "external_read_provider" and integration == "google_calendar":
            actions = tuple(allowed_actions or GOOGLE_CALENDAR_READ_ACTIONS)
            side_effects = tuple(allowed_side_effect_classes or GOOGLE_CALENDAR_READ_SIDE_EFFECTS)
            hosts = tuple(trusted_destination_hosts or GOOGLE_CALENDAR_TRUSTED_HOSTS)
            return actions, side_effects, hosts
        if provider == "external_read_provider" and integration == "google_contacts":
            actions = tuple(allowed_actions or GOOGLE_CONTACTS_READ_ACTIONS)
            side_effects = tuple(allowed_side_effect_classes or GOOGLE_CONTACTS_READ_SIDE_EFFECTS)
            hosts = tuple(trusted_destination_hosts or GOOGLE_CONTACTS_TRUSTED_HOSTS)
            return actions, side_effects, hosts
        if provider == "external_read_provider" and integration == "github":
            actions = tuple(allowed_actions or GITHUB_READ_ACTIONS)
            side_effects = tuple(allowed_side_effect_classes or GITHUB_READ_SIDE_EFFECTS)
            hosts = tuple(trusted_destination_hosts or GITHUB_TRUSTED_HOSTS)
            return actions, side_effects, hosts
        if provider == "external_read_provider" and integration == "linkedin":
            actions = tuple(allowed_actions or LINKEDIN_READ_ACTIONS)
            side_effects = tuple(allowed_side_effect_classes or LINKEDIN_READ_SIDE_EFFECTS)
            hosts = tuple(trusted_destination_hosts or LINKEDIN_TRUSTED_HOSTS)
            return actions, side_effects, hosts
        if provider == "external_read_provider" and integration == "salesforce":
            actions = tuple(allowed_actions or SALESFORCE_READ_ACTIONS)
            side_effects = tuple(allowed_side_effect_classes or SALESFORCE_READ_SIDE_EFFECTS)
            hosts = tuple(trusted_destination_hosts or ())
            if not hosts:
                derived_host = _salesforce_instance_host_from_secret(secret_value)
                if derived_host:
                    hosts = (derived_host,)
            if not hosts:
                raise ProviderCredentialManagementError(
                    "trusted_destination_hosts is required for salesforce integration "
                    "(tenant Salesforce instance host, e.g. mycompany.my.salesforce.com)"
                )
            return actions, side_effects, hosts
        if provider == "external_read_provider":
            actions = tuple(allowed_actions or ("provider.external_read",))
            side_effects = tuple(allowed_side_effect_classes or ("external_read",))
            hosts = tuple(trusted_destination_hosts or ("api.hubapi.com",))
            return actions, side_effects, hosts
        if provider == "external_email" and integration == "gmail":
            actions = tuple(allowed_actions or GMAIL_EMAIL_ACTIONS)
            side_effects = tuple(allowed_side_effect_classes or GMAIL_EMAIL_SIDE_EFFECTS)
            hosts = tuple(trusted_destination_hosts or ("gmail.googleapis.com",))
            return actions, side_effects, hosts
        if provider == "external_email" and integration == "smtp":
            actions = tuple(allowed_actions or SMTP_EMAIL_ACTIONS)
            side_effects = tuple(allowed_side_effect_classes or SMTP_EMAIL_SIDE_EFFECTS)
            hosts = tuple(trusted_destination_hosts or ())
            return actions, side_effects, hosts
        actions = tuple(allowed_actions or ())
        side_effects = tuple(allowed_side_effect_classes or ())
        hosts = tuple(trusted_destination_hosts or ())
        if not hosts:
            raise ProviderCredentialManagementError("trusted_destination_hosts is required for generic integrations")
        return actions, side_effects, hosts

    def _to_summary(self, row: ProviderRuntimeCredential) -> ProviderCredentialSummary:
        uses_platform = row.credential_type == PLATFORM_MASTER_CREDENTIAL_TYPE
        warning = None
        if uses_platform:
            if row.provider == "external_email":
                warning = (
                    "Platform master email mode: shared operator SMTP credential with elevated blast radius. "
                    "Rotate AJENDA_EMAIL_PLATFORM_SMTP_SECRET with care."
                )
            else:
                warning = (
                    "Platform master key mode: shared operator credential with elevated blast radius. "
                    "Rotate AJENDA_HUBSPOT_PLATFORM_MASTER_KEY with care."
                )
        return ProviderCredentialSummary(
            credential_id=row.credential_id,
            tenant_id=row.tenant_id,
            provider=row.provider,
            credential_type=row.credential_type,
            enabled=row.enabled,
            revoked=row.revoked,
            allowed_actions=list(row.allowed_actions or []),
            allowed_side_effect_classes=list(row.allowed_side_effect_classes or []),
            trusted_destination_hosts=list(row.trusted_destination_hosts or []),
            uses_platform_master_key=uses_platform,
            platform_master_warning=warning,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )

    def _resolve_credential_type(
        self,
        *,
        provider: str,
        integration: str,
        use_platform_master_key: bool,
    ) -> str:
        if use_platform_master_key:
            return PLATFORM_MASTER_CREDENTIAL_TYPE
        if provider == "external_email" and integration == "smtp":
            return "smtp"
        return TENANT_API_KEY_CREDENTIAL_TYPE

    @staticmethod
    def _validate_smtp_secret(secret_value: str) -> None:
        import json

        try:
            payload = json.loads(secret_value)
        except json.JSONDecodeError as exc:
            raise ProviderCredentialManagementError("smtp secret_value must be JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderCredentialManagementError("smtp secret_value must be a JSON object")
        for field in ("host", "password"):
            if not str(payload.get(field, "")).strip():
                raise ProviderCredentialManagementError(f"smtp secret_value requires {field}")
        user = payload.get("user", payload.get("username"))
        if not str(user or "").strip():
            raise ProviderCredentialManagementError("smtp secret_value requires user or username")

    def _emit_audit(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        action: str,
        details: str,
        payload: dict[str, object],
    ) -> None:
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=None,
                category="credentials",
                action=action,
                actor=actor_id,
                details=details,
                payload_json=payload,
            )
        )


def _salesforce_instance_host_from_secret(secret_value: str | None) -> str | None:
    if not secret_value or not secret_value.strip().startswith("{"):
        return None
    try:
        payload = json.loads(secret_value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    instance_url = payload.get("instance_url")
    if not isinstance(instance_url, str) or not instance_url.strip():
        return None
    from backend.services.credentials.salesforce_oauth_client import instance_host_from_url

    return instance_host_from_url(instance_url)


def _normalize_credential_id(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ProviderCredentialManagementError("credential_id is required")
    if len(stripped) > 160:
        raise ProviderCredentialManagementError("credential_id is too long")
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", stripped):
        raise ProviderCredentialManagementError("credential_id contains invalid characters")
    return stripped
