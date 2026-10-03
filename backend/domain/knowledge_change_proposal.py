from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class KnowledgeChangeProposalRecord(Base):
    """Tenant-owned lifecycle record for a review-only knowledge proposal."""

    __tablename__ = "knowledge_change_proposals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "proposal_id", name="uq_knowledge_change_proposals_tenant_identity"),
        Index("ix_knowledge_change_proposals_tenant_status", "tenant_id", "status"),
        Index("ix_knowledge_change_proposals_tenant_target", "tenant_id", "target_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    proposal_id: Mapped[str] = mapped_column(String(160), nullable=False)
    mission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("missions.id"), nullable=False)
    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("outcome_reviews.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    target_key: Mapped[str] = mapped_column(String(256), nullable=False)
    suggested_change: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    source_artifact_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    runtime_reconciliation: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="review_required")
    supersedes_proposal_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    superseded_by_proposal_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    rollback_of_proposal_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
