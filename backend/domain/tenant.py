"""Tenant domain model for Ajenda AI SaaS multi-tenancy.

Every resource in the system belongs to exactly one Tenant. The Tenant record
is the root of the SaaS hierarchy and governs:

  - Lifecycle state (active / suspended / deleted)
  - Subscription plan tier (free / starter / pro / enterprise)
  - Feature flags and usage limits derived from the plan
  - Soft-delete semantics (deleted_at is set; rows are never physically removed
    during the compliance retention window)

PostgreSQL RLS policies reference tenant_id on all child tables. The Tenant
table itself is accessible only to the ajenda_admin role.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Tenant(Base):
    """Root SaaS tenant record.

    One row per customer organisation. All child domain objects carry a
    tenant_id foreign key that is enforced by both application-layer queries
    and PostgreSQL Row-Level Security policies.
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        index=True,
        comment="active | suspended | deleted",
    )

    # Subscription plan
    plan: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="free",
        comment="free | starter | pro | enterprise",
    )

    # Soft-delete
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Audit timestamps
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
        """Return True only if this tenant can accept new work."""
        return self.status == "active" and self.deleted_at is None

    def is_suspended(self) -> bool:
        return self.status == "suspended"

    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} slug={self.slug!r} status={self.status!r} plan={self.plan!r}>"
