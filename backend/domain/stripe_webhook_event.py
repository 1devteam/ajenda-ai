"""Stripe webhook event receipt — idempotency and processing audit trail.

Each Stripe event ID (evt_...) is recorded at most once. Receipts capture the
processing outcome so webhook handling is observable and duplicate deliveries
are safely ignored.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class StripeWebhookEvent(Base):
    """Immutable receipt for a processed Stripe webhook event."""

    __tablename__ = "stripe_webhook_events"

    event_id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        comment="Stripe event ID (evt_...)",
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="Resolved tenant, if any",
    )
    outcome: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="processing | applied | skipped | ignored | duplicate",
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
