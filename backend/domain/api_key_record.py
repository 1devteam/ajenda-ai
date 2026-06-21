from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

API_KEY_PURPOSES = frozenset({"operational", "bootstrap"})


def _default_machine_executor_roles() -> list[str]:
    return ["machine_executor"]


def utcnow() -> datetime:
    return datetime.now(UTC)


class ApiKeyRecordModel(Base):
    __tablename__ = "api_key_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    hashed_secret: Mapped[str] = mapped_column(String(256), nullable=False)
    scopes_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="operational")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    roles_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=_default_machine_executor_roles,
    )
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=utcnow, onupdate=utcnow
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def key_hash(self) -> str:
        return self.hashed_secret
