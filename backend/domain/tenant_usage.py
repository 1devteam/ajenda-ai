"""TenantUsage domain model — real-time usage metering per billing period.

One row per (tenant_id, billing_period_start). The billing period is a
calendar month (first day of month, UTC). Counters are incremented atomically
using PostgreSQL UPDATE ... RETURNING to avoid race conditions.

Design decisions:
  - Separate from TenantPlan so that usage can be queried without joining
    the plan table on every API call.
  - billing_period_start is the first day of the current UTC month. A new
    row is inserted automatically by the QuotaEnforcementService when the
    first event of a new billing period arrives.
  - All counters are BigInteger to handle high-volume enterprise tenants.
  - api_calls_count is incremented by the RateLimitMiddleware, not the
    quota service, to keep the hot path lightweight.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class TenantUsage(Base):
    """Monthly usage counters for a single tenant.

    All counters start at 0 and are incremented in-place. The quota
    enforcement service reads these values and compares them against the
    limits defined in TenantPlan before accepting new work.
    """

    __tablename__ = "tenant_usage"
    __table_args__ = (UniqueConstraint("tenant_id", "billing_period_start", name="uq_tenant_usage_period"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    billing_period_start: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="First day of the billing month (UTC)",
    )

    # --- Metered counters ---
    missions_created: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tasks_created: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    api_calls_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    agents_provisioned: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # --- Gauge (point-in-time, not cumulative) ---
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

    def __repr__(self) -> str:
        return (
            f"<TenantUsage tenant={self.tenant_id} period={self.billing_period_start} "
            f"missions={self.missions_created} tasks={self.tasks_created}>"
        )
