from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class KnowledgeQualificationRecord(Base):
    """Immutable tenant-owned history of an upstream qualification result."""

    __tablename__ = "knowledge_qualification_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "qualification_id", name="uq_knowledge_qualification_tenant_identity"),
        UniqueConstraint("id", "tenant_id", name="uq_knowledge_qualification_id_tenant"),
        Index("ix_knowledge_qualification_tenant_proposition", "tenant_id", "proposition_key"),
        Index("ix_knowledge_qualification_tenant_status", "tenant_id", "qualification_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    qualification_id: Mapped[str] = mapped_column(String(128), nullable=False)
    proposition_key: Mapped[str] = mapped_column(String(128), nullable=False)
    qualification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_candidate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evaluation_watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    qualification_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class KnowledgeArtifactRecord(Base):
    """Immutable tenant-owned durable wrapper around a qualified artifact."""

    __tablename__ = "knowledge_artifact_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "knowledge_id", name="uq_knowledge_artifact_tenant_identity"),
        UniqueConstraint("tenant_id", "qualification_id", name="uq_knowledge_artifact_tenant_qualification"),
        ForeignKeyConstraint(
            ("qualification_record_id", "tenant_id"),
            ("knowledge_qualification_records.id", "knowledge_qualification_records.tenant_id"),
            name="fk_knowledge_artifact_qualification_tenant",
        ),
        Index("ix_knowledge_artifact_tenant_proposition", "tenant_id", "proposition_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    qualification_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    knowledge_id: Mapped[str] = mapped_column(String(128), nullable=False)
    proposition_key: Mapped[str] = mapped_column(String(128), nullable=False)
    qualification_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_candidate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    qualified_through_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proposition_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    artifact_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
