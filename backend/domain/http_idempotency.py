"""Durable control-plane receipts for HTTP idempotency ownership.

The table intentionally stores only hashed operation/request identities. It has no
``tenant_id`` column because it coordinates both authenticated tenant traffic and
pre-tenant public authentication/onboarding traffic. Replay payloads are encrypted
before persistence by ``HttpIdempotencyAuthority``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

HTTP_IDEMPOTENCY_STATUS_CLAIMING = "claiming"
HTTP_IDEMPOTENCY_STATUS_COMPLETED = "completed"


class HttpIdempotencyReceipt(Base):
    """One durable ownership record for a scoped HTTP idempotency operation."""

    __tablename__ = "http_idempotency_receipts"
    __table_args__ = (
        UniqueConstraint("operation_key", name="uq_http_idempotency_operation_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_token: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
