from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class TenantUsage(Base):
    """Monthly tenant usage counters."""

    __tablename__ = "tenant_usage"
    __table_args__ = (
        UniqueConstraint("tenant_id", "billing_period_start", name="uq_tenant_usage_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    billing_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    missions_created: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tasks_created: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    api_calls_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    agents_provisioned: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    active_workers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
