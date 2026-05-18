from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

UNLIMITED = -1


class TenantPlan(Base):
    """Subscription plan definition and limit contract."""

    __tablename__ = "tenant_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    max_missions_per_month: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_tasks_per_month: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    max_agents_per_fleet: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_concurrent_workers: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    max_api_keys: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_monthly_api_calls: Mapped[int] = mapped_column(BigInteger, nullable=False, default=10_000)
    features_enabled: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
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
        return feature in (self.features_enabled or [])

    def check_limit(self, field: str, current_count: int) -> bool:
        limit: Any = getattr(self, field, UNLIMITED)
        if limit == UNLIMITED:
            return True
        return current_count < int(limit)
