from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ApiKeyRecordModel(Base):
    __tablename__ = "api_key_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    hashed_secret: Mapped[str] = mapped_column(String(128), nullable=False)
    scopes_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


    @property
    def key_hash(self) -> str:
        return self.hashed_secret
