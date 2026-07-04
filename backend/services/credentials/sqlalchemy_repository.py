from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.services.credentials.github_runtime_token import (
    GitHubRuntimeTokenError,
    GitHubRuntimeTokenResolution,
    is_github_oauth_secret,
    resolve_github_credential_secret,
)
from backend.services.credentials.gmail_runtime_token import (
    GmailRuntimeTokenError,
    resolve_gmail_credential_secret,
)
from backend.services.credentials.google_calendar_runtime_token import (
    GoogleCalendarRuntimeTokenError,
    GoogleCalendarRuntimeTokenResolution,
    is_google_calendar_oauth_secret,
    resolve_google_calendar_credential_secret,
)
from backend.services.credentials.linkedin_runtime_token import (
    LinkedInRuntimeTokenError,
    LinkedInRuntimeTokenResolution,
    is_linkedin_oauth_secret,
    resolve_linkedin_credential_secret,
)
from backend.services.credentials.management_service import (
    PLATFORM_MASTER_CREDENTIAL_TYPE,
    PLATFORM_MASTER_SENTINEL,
)
from backend.services.credentials.platform_master import (
    PlatformMasterNotConfiguredError,
    resolve_platform_master_secret,
)
from backend.services.credentials.runtime_authority import CredentialRecord, CredentialRuntimeRepository
from backend.services.credentials.salesforce_runtime_token import (
    SalesforceRuntimeTokenError,
    SalesforceRuntimeTokenResolution,
    is_salesforce_oauth_secret,
    resolve_salesforce_credential_secret,
)
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector
from backend.services.tools.schemas import SideEffectClass


class SQLAlchemyCredentialRuntimeRepository(CredentialRuntimeRepository):
    """Live SQLAlchemy-backed credential runtime repository.

    This repository is intentionally thin: it loads tenant-scoped credential
    metadata and decrypts the ciphertext secret immediately before returning a
    ``CredentialRecord`` to ``CredentialRuntimeAuthority``. Authorization and
    compatibility checks remain inside ``CredentialRuntimeAuthority``.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        secret_protector: RuntimeCredentialSecretProtector | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._secret_protector = secret_protector or RuntimeCredentialSecretProtector()

    def get_visible_for_tenant(self, *, tenant_id: str, credential_id: str) -> CredentialRecord | None:
        session = self._session_factory()
        try:
            row = session.execute(
                select(ProviderRuntimeCredential).where(
                    ProviderRuntimeCredential.tenant_id == tenant_id,
                    ProviderRuntimeCredential.credential_id == credential_id,
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return self._to_credential_record(row, session=session)
        finally:
            session.close()

    def _to_credential_record(self, row: ProviderRuntimeCredential, *, session: Session) -> CredentialRecord:
        secret_value = self._resolve_secret_value(row, session=session)
        return CredentialRecord(
            credential_id=row.credential_id,
            tenant_id=row.tenant_id,
            provider=row.provider,
            credential_type=row.credential_type,
            enabled=row.enabled,
            revoked=row.revoked,
            deleted=row.deleted,
            allowed_actions=tuple(_string_items(row.allowed_actions)),
            allowed_side_effect_classes=tuple(
                SideEffectClass(item) for item in _string_items(row.allowed_side_effect_classes)
            ),
            trusted_destination_hosts=tuple(_string_items(row.trusted_destination_hosts)),
            secret_value=secret_value,
        )

    def _resolve_secret_value(self, row: ProviderRuntimeCredential, *, session: Session) -> str:
        if row.credential_type == PLATFORM_MASTER_CREDENTIAL_TYPE:
            return self._resolve_platform_master(row)
        decrypted = self._secret_protector.decrypt_secret(row.secret_ciphertext)
        if decrypted == PLATFORM_MASTER_SENTINEL:
            return self._resolve_platform_master(row)
        if row.provider == "external_email" and row.credential_type == "api_key":
            return self._resolve_gmail_secret(row=row, decrypted=decrypted, session=session)
        if row.provider == "external_read_provider" and row.credential_type == "api_key":
            return self._resolve_external_read_secret(row=row, decrypted=decrypted, session=session)
        return decrypted

    @staticmethod
    def _resolve_platform_master(row: ProviderRuntimeCredential) -> str:
        integration = "smtp" if row.provider == "external_email" else "hubspot"
        try:
            return resolve_platform_master_secret(provider=row.provider, integration=integration)
        except PlatformMasterNotConfiguredError as exc:
            raise ValueError(str(exc)) from exc

    def _resolve_gmail_secret(self, *, row: ProviderRuntimeCredential, decrypted: str, session: Session) -> str:
        settings = get_settings()
        try:
            resolution = resolve_gmail_credential_secret(
                decrypted,
                auto_refresh=True,
                redirect_uri=settings.gmail_oauth_redirect_uri,
            )
        except GmailRuntimeTokenError as exc:
            raise ValueError(str(exc)) from exc
        if resolution.updated_secret and resolution.updated_secret != decrypted:
            row.secret_ciphertext = self._secret_protector.encrypt_secret(resolution.updated_secret)
            session.add(row)
            session.commit()
        return resolution.access_token

    def _resolve_external_read_secret(self, *, row: ProviderRuntimeCredential, decrypted: str, session: Session) -> str:
        settings = get_settings()
        trusted_hosts = _string_items(row.trusted_destination_hosts)
        resolution: (
            SalesforceRuntimeTokenResolution
            | GoogleCalendarRuntimeTokenResolution
            | GitHubRuntimeTokenResolution
            | LinkedInRuntimeTokenResolution
        )
        if is_salesforce_oauth_secret(decrypted) or any(".salesforce.com" in host for host in trusted_hosts):
            try:
                resolution = resolve_salesforce_credential_secret(
                    decrypted,
                    auto_refresh=True,
                    redirect_uri=settings.salesforce_oauth_redirect_uri,
                )
            except SalesforceRuntimeTokenError as exc:
                raise ValueError(str(exc)) from exc
        elif is_google_calendar_oauth_secret(decrypted) or "www.googleapis.com" in trusted_hosts:
            try:
                resolution = resolve_google_calendar_credential_secret(
                    decrypted,
                    auto_refresh=True,
                    redirect_uri=settings.google_calendar_oauth_redirect_uri,
                )
            except GoogleCalendarRuntimeTokenError as exc:
                raise ValueError(str(exc)) from exc
        elif is_github_oauth_secret(decrypted) or "api.github.com" in trusted_hosts:
            try:
                resolution = resolve_github_credential_secret(
                    decrypted,
                    auto_refresh=True,
                    redirect_uri=settings.github_oauth_redirect_uri,
                )
            except GitHubRuntimeTokenError as exc:
                raise ValueError(str(exc)) from exc
        elif is_linkedin_oauth_secret(decrypted) or "api.linkedin.com" in trusted_hosts:
            try:
                resolution = resolve_linkedin_credential_secret(
                    decrypted,
                    auto_refresh=True,
                    redirect_uri=settings.linkedin_oauth_redirect_uri,
                )
            except LinkedInRuntimeTokenError as exc:
                raise ValueError(str(exc)) from exc
        else:
            return decrypted

        if resolution.updated_secret and resolution.updated_secret != decrypted:
            row.secret_ciphertext = self._secret_protector.encrypt_secret(resolution.updated_secret)
            session.add(row)
            session.commit()
        return resolution.access_token


def _string_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    raise ValueError("credential runtime metadata must be stored as a list")
