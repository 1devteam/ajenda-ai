"""WebhookDelivery domain model — immutable record of a single delivery attempt.

Design decisions:
  - Every delivery attempt (success or failure) is recorded as an immutable row.
  - Retries create new WebhookDelivery rows rather than mutating existing ones,
    preserving the full delivery history for debugging and audit.
  - The response_body is capped at 4096 characters to prevent runaway storage
    from verbose error responses.
  - Delivery status transitions: PENDING → DELIVERING → DELIVERED | FAILED
  - After max_attempts failures, the endpoint is automatically disabled and a
    dead_lettered status is set on the latest delivery row.

Retry policy:
  Attempt 1: immediate
  Attempt 2: 30 seconds
  Attempt 3: 5 minutes
  Attempt 4: 30 minutes
  Attempt 5: 2 hours
  After 5 failures: endpoint disabled, operator notified via audit event
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

# Maximum characters stored from the response body
RESPONSE_BODY_MAX_CHARS = 4096


class WebhookDelivery(Base):
    """A single delivery attempt for a webhook event.

    Created by WebhookDispatchService for every (endpoint, event) pair.
    Immutable after creation — retries create new rows.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="FK to webhook_endpoints.id",
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Denormalised for efficient tenant-scoped queries",
    )
    # Event metadata
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="e.g. task.completed, compliance.review_required",
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Unique ID for this event — used for idempotency on retries",
    )
    # Payload delivered to the endpoint
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Full JSON payload sent in the POST body",
    )
    # Delivery outcome
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
        comment="pending | delivering | delivered | failed | dead_lettered",
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="1-based attempt counter for this event_id",
    )
    http_status_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="HTTP status code returned by the endpoint, if a response was received",
    )
    response_body: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment=f"First {RESPONSE_BODY_MAX_CHARS} chars of the response body",
    )
    error_message: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="Network or timeout error message if no HTTP response was received",
    )
    # Timing
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="When this delivery attempt was initiated",
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When a 2xx response was received",
    )

    @property
    def succeeded(self) -> bool:
        """Return True if this delivery attempt received a 2xx response."""
        return self.status == "delivered"

    @property
    def is_terminal(self) -> bool:
        """Return True if this attempt reached a terminal state."""
        return self.status in {"delivered", "dead_lettered"}

    def __repr__(self) -> str:
        return (
            f"<WebhookDelivery id={self.id} endpoint={self.endpoint_id} "
            f"event={self.event_type!r} status={self.status!r} "
            f"attempt={self.attempt_number}>"
        )
