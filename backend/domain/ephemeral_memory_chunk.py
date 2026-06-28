from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.vector_base import VectorBase


class EphemeralMemoryChunk(VectorBase):
    """Tenant-scoped ephemeral memory chunk stored on the vector data plane."""

    __tablename__ = "ephemeral_memory_chunks"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    mission_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding_json: Mapped[list[float]] = mapped_column(JSONB, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(120), nullable=False, default="runtime")
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )