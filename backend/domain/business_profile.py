from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

BUSINESS_PROFILE_SCHEMA_VERSION = 1
BUSINESS_PROFILE_SUGGESTION_SCHEMA_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(UTC)


class BusinessProfile(Base):
    """Tenant-owned durable business context.

    Business profiles store approved reusable facts only. They do not create
    missions, generate Mission Briefs, enqueue work, dispatch workers, promote
    memory, or mutate runtime execution state.
    """

    __tablename__ = "business_profiles"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('active', 'archived', 'superseded')",
            name="ck_business_profiles_status",
        ),
        sa.Index(
            "uq_business_profiles_active_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    approved_facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=BUSINESS_PROFILE_SCHEMA_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class BusinessProfileSuggestion(Base):
    """Tenant-owned proposal for durable Business Profile updates.

    Suggestions are not approved profile truth until explicitly approved or
    edited-and-approved by a user/operator. Declined or dismissed suggestions do
    not mutate approved facts.
    """

    __tablename__ = "business_profile_suggestions"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'edited', 'declined', 'dismissed', 'superseded')",
            name="ck_business_profile_suggestions_status",
        ),
        sa.Index(
            "ix_business_profile_suggestions_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("status", "pending")
        kwargs.setdefault("resolution", {})
        kwargs.setdefault("source_context", {})
        kwargs.setdefault("suggested_fact", {})
        super().__init__(**kwargs)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_profiles.id"), nullable=True, index=True
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("missions.id"), nullable=True, index=True
    )
    suggested_category: Mapped[str] = mapped_column(String(96), nullable=False)
    suggested_fact: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    rationale: Mapped[str] = mapped_column(String(500), nullable=False)
    source_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    resolution: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=BUSINESS_PROFILE_SUGGESTION_SCHEMA_VERSION
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
