from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class TenantInternalRecord(Base):
    """Durable tenant-scoped CRM substitute for Ajenda standalone brain mode."""

    __tablename__ = "tenant_internal_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "record_type",
            "record_id",
            name="uq_tenant_internal_records_tenant_type_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    record_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    data_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
