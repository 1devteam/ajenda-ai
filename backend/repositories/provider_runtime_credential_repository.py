from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.domain.provider_runtime_credential import ProviderRuntimeCredential


class ProviderRuntimeCredentialRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_tenant(self, *, tenant_id: str, credential_id: str) -> ProviderRuntimeCredential | None:
        stmt = select(ProviderRuntimeCredential).where(
            ProviderRuntimeCredential.tenant_id == tenant_id,
            ProviderRuntimeCredential.credential_id == credential_id,
            ProviderRuntimeCredential.deleted.is_(False),
        )
        return self._session.scalars(stmt).first()

    def _get_any_for_tenant(self, *, tenant_id: str, credential_id: str) -> ProviderRuntimeCredential | None:
        stmt = select(ProviderRuntimeCredential).where(
            ProviderRuntimeCredential.tenant_id == tenant_id,
            ProviderRuntimeCredential.credential_id == credential_id,
        )
        return self._session.scalars(stmt).first()

    def list_for_tenant(self, *, tenant_id: str) -> list[ProviderRuntimeCredential]:
        stmt = (
            select(ProviderRuntimeCredential)
            .where(
                ProviderRuntimeCredential.tenant_id == tenant_id,
                ProviderRuntimeCredential.deleted.is_(False),
            )
            .order_by(ProviderRuntimeCredential.created_at.desc())
        )
        return list(self._session.scalars(stmt).all())

    def upsert(self, record: ProviderRuntimeCredential) -> ProviderRuntimeCredential:
        existing = self.get_for_tenant(tenant_id=record.tenant_id, credential_id=record.credential_id)
        if existing is None:
            existing = self._get_any_for_tenant(
                tenant_id=record.tenant_id,
                credential_id=record.credential_id,
            )
        now = datetime.now(UTC)
        if existing is None:
            if not record.id:
                record.id = f"prc-{uuid.uuid4()}"
            record.created_at = now
            record.updated_at = now
            self._session.add(record)
            try:
                self._session.flush()
            except IntegrityError:
                self._session.rollback()
                existing = self._get_any_for_tenant(
                    tenant_id=record.tenant_id,
                    credential_id=record.credential_id,
                )
                if existing is None:
                    raise
            else:
                self._session.refresh(record)
                return record

        existing.provider = record.provider
        existing.integration = record.integration
        existing.credential_type = record.credential_type
        existing.enabled = record.enabled
        existing.revoked = False
        existing.deleted = False
        existing.allowed_actions = record.allowed_actions
        existing.allowed_side_effect_classes = record.allowed_side_effect_classes
        existing.trusted_destination_hosts = record.trusted_destination_hosts
        existing.secret_ciphertext = record.secret_ciphertext
        existing.updated_at = now
        self._session.flush()
        self._session.refresh(existing)
        return existing

    def mark_revoked(self, *, tenant_id: str, credential_id: str) -> ProviderRuntimeCredential:
        record = self.get_for_tenant(tenant_id=tenant_id, credential_id=credential_id)
        if record is None:
            raise ValueError("provider credential not found")
        record.revoked = True
        record.enabled = False
        record.updated_at = datetime.now(UTC)
        self._session.flush()
        return record

    def mark_deleted(self, *, tenant_id: str, credential_id: str) -> ProviderRuntimeCredential:
        record = self.get_for_tenant(tenant_id=tenant_id, credential_id=credential_id)
        if record is None:
            raise ValueError("provider credential not found")
        record.deleted = True
        record.enabled = False
        record.updated_at = datetime.now(UTC)
        self._session.flush()
        return record
