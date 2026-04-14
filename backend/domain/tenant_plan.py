"""TenantPlan domain model — subscription tier limits and feature flags.

Each Tenant has exactly one active plan. Plans define hard limits that are
enforced at the API layer by QuotaEnforcementService before any work is
accepted into the system.

Design decisions:
  - Plans are stored as rows in the database (not hardcoded enums) so that
    enterprise customers can have custom limits without a code deployment.
  - The plan slug matches the Tenant.plan field — this is the join key.
  - All limit fields use -1 as the sentinel value for "unlimited".
  - Feature flags are stored as a JSON array of feature strings so that new
    features can be gated without schema migrations.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

# Sentinel: -1 means unlimited for any integer limit field.
UNLIMITED = -1


class TenantPlan(Base):
    """Subscription plan definition.

    One row per plan tier (free, starter, pro, enterprise, and any custom
    enterprise overrides). The slug is the join key to Tenant.plan.
    """

    __tablename__ = "tenant_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
        comment="Matches Tenant.plan — join key",
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # --- Hard limits ---
    # -1 = unlimited
    max_missions_per_month: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_tasks_per_month: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    max_agents_per_fleet: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    max_concurrent_workers: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_api_keys: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    max_monthly_api_calls: Mapped[int] = mapped_column(BigInteger, nullable=False, default=10_000)

    # --- Feature flags ---
    # JSON array of feature strings, e.g. ["compliance_layer", "custom_webhooks"]
    features_enabled: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Array of feature flag strings enabled for this plan",
    )

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

    def allows_feature(self, feature: str) -> bool:
        """Return True if this plan includes the given feature flag."""
        return feature in (self.features_enabled or [])

    def check_limit(self, field: str, current_count: int) -> bool:
        """Return True if current_count is within the plan limit for field.

        Returns True unconditionally if the limit is UNLIMITED (-1).
        """
        limit = getattr(self, field, UNLIMITED)
        if limit == UNLIMITED:
            return True
        return current_count < limit

    def __repr__(self) -> str:
        return f"<TenantPlan slug={self.slug!r} display={self.display_name!r}>"
