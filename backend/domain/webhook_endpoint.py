"""WebhookEndpoint domain model — tenant-scoped outbound webhook registration.

Design decisions:
  - Each tenant can register multiple webhook endpoints (up to their plan limit).
  - Each endpoint has a randomly-generated HMAC-SHA256 signing secret stored
    as a bcrypt hash. The plaintext secret is shown once at registration and
    never stored in plaintext.
  - Tenants subscribe to specific event types (e.g. task.completed) rather
    than receiving all events, reducing noise and payload volume.
  - Endpoints can be disabled without deletion, preserving configuration.
  - Delivery attempts are tracked in WebhookDelivery (separate model).

Event type vocabulary (mirrors ExecutionTaskState transitions):
  task.queued          — task moved to QUEUED state
  task.running         — task moved to RUNNING state
  task.completed       — task moved to COMPLETED state
  task.failed          — task moved to FAILED state
  task.dead_lettered   — task moved to DEAD_LETTERED state
  task.recovering      — task moved to RECOVERING state
  mission.completed    — all tasks in a mission reached terminal state
  compliance.review_required — task flagged for human review

SQLite compatibility:
  The event_types column uses a StringArray TypeDecorator that renders as
  ARRAY(String) on PostgreSQL (for efficient @> containment queries) and as
  JSON on SQLite (for unit test compatibility). This is the same pattern used
  for JSONB columns elsewhere in the codebase.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy import types as sa_types
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class StringArray(sa_types.TypeDecorator):
    """A list-of-strings column that renders as ARRAY on PostgreSQL and JSON on SQLite.

    This allows unit tests to run against an in-memory SQLite database while
    production uses the more efficient PostgreSQL ARRAY type with @> containment
    support.
    """

    impl = sa_types.Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.ARRAY(String(64)))
        return dialect.type_descriptor(sa_types.Text())

    def process_bind_param(self, value: list[str] | None, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Any) -> list[str]:
        if value is None:
            return []
        if dialect.name == "postgresql":
            return value
        if isinstance(value, list):
            return value
        return json.loads(value)


class WebhookEndpoint(Base):
    """A registered outbound webhook endpoint for a tenant.

    Tenants register one or more HTTPS URLs to receive event notifications.
    Each endpoint has a signing secret used to generate HMAC-SHA256 signatures
    on the ``X-Ajenda-Signature-256`` header of every delivery attempt.
    """

    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Owning tenant — enforced at the application layer",
    )
    # Target URL — must be HTTPS in production
    url: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
        comment="HTTPS URL to deliver events to",
    )
    # HMAC signing secret — stored as bcrypt hash; plaintext returned once at creation
    secret_hash: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        comment="bcrypt hash of the HMAC signing secret",
    )
    # Subscribed event types — ARRAY on PostgreSQL, JSON text on SQLite
    event_types: Mapped[list[str]] = mapped_column(
        StringArray,
        nullable=False,
        default=list,
        comment="Array of event type strings this endpoint subscribes to",
    )
    # Lifecycle
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="False = endpoint disabled; deliveries are skipped",
    )
    # Audit timestamps
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

    def subscribes_to(self, event_type: str) -> bool:
        """Return True if this endpoint is subscribed to the given event type."""
        return self.is_active and event_type in (self.event_types or [])

    def __repr__(self) -> str:
        return (
            f"<WebhookEndpoint id={self.id} tenant={self.tenant_id} "
            f"url={self.url!r} active={self.is_active}>"
        )
