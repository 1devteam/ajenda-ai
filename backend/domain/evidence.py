from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

EVIDENCE_CONTRACT_SCHEMA_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(UTC)


class EvidenceRecord(Base):
    """Durable tenant-owned evidence contract.

    Evidence records are proof/provenance data only. They intentionally do not
    score outcomes, promote memory, execute adapters, enqueue work, dispatch
    workers, or call runtime orchestration services.
    """

    __tablename__ = "evidence_records"
    __table_args__ = (
        # Logical identity is intentionally opt-in.  Canonical runtime evidence
        # ordinarily represents one task-output projection; learning episodes
        # additionally need a tenant-scoped, write-time identity so competing
        # materializers cannot persist two records for one verified episode.
        Index(
            "uq_evidence_records_tenant_logical_identity",
            "tenant_id",
            "logical_identity",
            unique=True,
            postgresql_where=text("logical_identity IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("missions.id"), nullable=False, index=True
    )
    task_graph_node_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    materialization_reference: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    execution_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_tasks.id"), nullable=True, index=True
    )
    capability_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capabilities.id"), nullable=True, index=True
    )
    capability_adapter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capability_adapters.id"), nullable=True, index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_source: Mapped[str] = mapped_column(String(160), nullable=False)
    logical_identity: Mapped[str | None] = mapped_column(String(192), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    structured_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    artifact_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    provenance_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    trust_signal: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    collection_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=EVIDENCE_CONTRACT_SCHEMA_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
