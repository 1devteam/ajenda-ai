from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class AssuranceSnapshot(Base):
    """Append-only tenant-scoped continuous-assurance observation."""

    __tablename__ = "assurance_snapshots"
    __table_args__ = (
        Index("ix_assurance_snapshots_tenant_observed", "tenant_id", "observed_at"),
        Index("ix_assurance_snapshots_tenant_status", "tenant_id", "status"),
        Index("ix_assurance_snapshots_mission_observed", "mission_id", "observed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("missions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    first_divergence: Mapped[str | None] = mapped_column(String(500), nullable=True)
    finding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    runtime_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    reconciliation_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    epistemic_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    calibration_outcome_aligned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    authority_class: Mapped[str] = mapped_column(String(32), nullable=False, default="read_model")
    grants_execution_authority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AssuranceMetricState(Base):
    """Singleton cross-tenant aggregate for operational monitoring only."""

    __tablename__ = "assurance_metric_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    snapshot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aligned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    incomplete_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    drifted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradictory_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_divergence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calibration_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calibration_aligned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
