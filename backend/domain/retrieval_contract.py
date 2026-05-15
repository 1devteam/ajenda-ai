from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

RETRIEVAL_CONTRACT_SCHEMA_VERSION = 1
RETRIEVAL_STATUSES = ("requested", "fulfilled", "rejected", "superseded", "revoked")
RETRIEVAL_STRATEGIES = ("semantic", "keyword", "hybrid", "operator_selected", "policy_selected", "procedural")


def utcnow() -> datetime:
    return datetime.now(UTC)


class RetrievalContract(Base):
    """Durable tenant-owned retrieval and recall contract.

    Retrieval contracts are governance-first records only. They intentionally do
    not execute vector search, generate embeddings, rank memories, reason over
    runtime state, enqueue work, dispatch workers, call runtime orchestration
    services, or mutate memory promotion records.
    """

    __tablename__ = "retrieval_contracts"
    __table_args__ = (
        CheckConstraint(
            "retrieval_status IN ('requested', 'fulfilled', 'rejected', 'superseded', 'revoked')",
            name="ck_retrieval_contracts_retrieval_status",
        ),
        CheckConstraint(
            "retrieval_strategy IN ('semantic', 'keyword', 'hybrid', 'operator_selected', 'policy_selected', 'procedural')",
            name="ck_retrieval_contracts_retrieval_strategy",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("missions.id"), nullable=False, index=True
    )
    retrieval_request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    retrieval_reason: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    retrieval_filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    governance_constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    memory_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    returned_memory_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    trust_signal: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    retrieval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="requested")
    superseded_by_retrieval_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    revocation_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=RETRIEVAL_CONTRACT_SCHEMA_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
