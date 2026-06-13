from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class ProviderRuntimeCredential(Base):
    """Tenant-scoped runtime credential record for provider tool actions.

    Secret values are stored as encrypted ciphertext and are only decrypted by
    the credential runtime repository immediately before returning material to
    ``CredentialRuntimeAuthority``.
    """

    __tablename__ = "provider_runtime_credentials"
    __table_args__ = (
        UniqueConstraint("tenant_id", "credential_id", name="uq_provider_runtime_credentials_tenant_credential"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    credential_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    credential_type: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    allowed_side_effect_classes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    trusted_destination_hosts: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
