from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.services.credentials.runtime_authority import CredentialRecord, CredentialRuntimeRepository
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
            return self._to_credential_record(row)
        finally:
            session.close()

    def _to_credential_record(self, row: ProviderRuntimeCredential) -> CredentialRecord:
        secret_value = self._secret_protector.decrypt_secret(row.secret_ciphertext)
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


def _string_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    raise ValueError("credential runtime metadata must be stored as a list")
