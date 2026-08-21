"""TenantMember — links a human identity to a tenant with a role."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

TENANT_MEMBER_ROLES = frozenset({"tenant_owner", "tenant_admin", "operator", "viewer"})
TENANT_MEMBER_STATUSES = frozenset({"pending_verification", "active", "revoked"})
VERIFICATION_DELIVERY_STATUSES = frozenset({"pending", "sent", "failed"})


class TenantMember(Base):
    """Cross-tenant membership registry row (no RLS — see migration 0028)."""

    __tablename__ = "tenant_members"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    email_raw: Mapped[str] = mapped_column(String(320), nullable=False)
    email_canonical: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="tenant_owner")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_verification")
    external_subject_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    verification_token_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_delivery_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def is_active(self) -> bool:
        return self.status == "active"

    def is_pending_verification(self) -> bool:
        return self.status == "pending_verification"
