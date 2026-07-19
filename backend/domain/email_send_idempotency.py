"""Durable receipts for SMTP (and other non-provider-idempotent) email sends.

Gmail API path relies on the outbound Idempotency-Key header. SMTP has no
provider-side dedupe, so Ajenda claims the key in this table *before* calling
sendmail. Worker retries under the same key must not deliver a second message.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

# claiming: insert won the race; send not yet finalized
# completed: send succeeded; result_payload is the replayable outcome
# (failed claims are deleted so a later retry may re-claim)
EMAIL_SEND_CLAIM_STATUS_CLAIMING = "claiming"
EMAIL_SEND_CLAIM_STATUS_COMPLETED = "completed"


class EmailSendIdempotencyReceipt(Base):
    """Tenant-scoped claim for one (action, idempotency_key) email send."""

    __tablename__ = "email_send_idempotency_receipts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "action",
            "idempotency_key",
            name="uq_email_send_idempotency_tenant_action_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="claiming | completed",
    )
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
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
