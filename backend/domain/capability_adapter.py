from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

CAPABILITY_ADAPTER_SCHEMA_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(UTC)


class CapabilityAdapter(Base):
    """Declarative capability execution adapter contract.

    Adapters describe how capability registry declarations may eventually bind
    to executable adapter surfaces. They intentionally do not register runtime
    handlers, enqueue work, create execution tasks, or execute tools.
    """

    __tablename__ = "capability_adapters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0.0")
    capability_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capabilities.id"), nullable=True, index=True
    )
    capability_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    capability_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supported_task_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    input_contract: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_contract: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    required_permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    required_tools: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="declarative")
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    approval_requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_expectations: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    timeout_retry_hints: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_expectations: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    side_effect_classification: Mapped[str] = mapped_column(String(64), nullable=False, default="none")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=CAPABILITY_ADAPTER_SCHEMA_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
