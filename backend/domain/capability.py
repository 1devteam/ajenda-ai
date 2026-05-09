from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

CAPABILITY_REGISTRY_SCHEMA_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(UTC)


class Capability(Base):
    """Declarative capability registry contract.

    Capabilities describe what future planning/task-graph layers may reference.
    They intentionally do not bind runtime handlers, enqueue work, or execute
    worker logic.
    """

    __tablename__ = "capabilities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0.0")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    supported_task_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    input_schema_hints: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_schema_hints: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    required_permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    required_tools: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    approval_requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_expectations: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    execution_constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=CAPABILITY_REGISTRY_SCHEMA_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
