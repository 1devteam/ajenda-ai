from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.domain.mission import utcnow
from backend.db.base import Base
from backend.domain.enums import ExecutionTaskState


class ExecutionTask(Base):
    __tablename__ = "execution_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    fleet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workforce_fleets.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_branches.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_workforce_agents.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ExecutionTaskState.PLANNED.value
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # --- Compliance fields (migration 0005) ---
    compliance_category: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="ComplianceCategory enum value - drives PolicyGuardian enforcement",
    )
    jurisdiction: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
        comment="ComplianceJurisdiction enum value - determines which regulatory ruleset applies",
    )
    requires_human_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Set by PolicyGuardian when task requires human review before execution",
    )
    compliance_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Structured compliance evidence: technical_doc_url, bias_audit_date, opt_out_url, etc.",
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
