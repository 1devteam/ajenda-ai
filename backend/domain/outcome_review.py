from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

OUTCOME_REVIEW_SCHEMA_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(UTC)


class OutcomeReview(Base):
    """Durable tenant-owned outcome review contract.

    Outcome reviews are review records only. They evaluate mission result claims
    against success criteria and evidence references without promoting memory,
    executing adapters, queueing work, dispatching workers, or mutating runtime
    mission/task state.
    """

    __tablename__ = "outcome_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("missions.id"), nullable=False, index=True
    )
    outcome_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    materialization_reference: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    task_graph_reference: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reviewed_success_criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    review_decision: Mapped[str] = mapped_column(String(32), nullable=False, default="inconclusive")
    reviewer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_source: Mapped[str] = mapped_column(String(160), nullable=False)
    review_summary: Mapped[str] = mapped_column(Text, nullable=False)
    structured_findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    trust_signal: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    unresolved_gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    recommended_next_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    human_approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    human_approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_required")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=OUTCOME_REVIEW_SCHEMA_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
