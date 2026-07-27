"""Durable mission composition proposal / interpretation history (declarative only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class MissionCompositionProposal(Base):
    """Backend-owned composition proposal history.

    Does not grant runtime execution authority. Used for audit, restatement loop
    prevention, supersession, and interpretation-quality analysis.
    """

    __tablename__ = "mission_composition_proposals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "proposal_id", name="uq_mission_composition_proposals_tenant_proposal"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    proposal_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    interpreter_version: Mapped[str] = mapped_column(String(40), nullable=False, default="3")
    components_active: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    record_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ready_to_start: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    restatement_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    recognized_clauses: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    unmatched_clauses: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    unresolved_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    canonical_outcomes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    send_policy_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    coverage_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    repeated_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    superseded_proposal_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    superseding_proposal_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    # active | failed | ready | superseded | confirmed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
