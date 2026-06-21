"""SignupAttemptLog — abuse observability for onboarding ingress."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

SIGNUP_ATTEMPT_OUTCOMES = frozenset(
    {
        "accepted",
        "duplicate_email",
        "rate_limited",
        "invalid_input",
        "error",
        "delivery_failed",
    }
)


class SignupAttemptLog(Base):
    """Append-only signup abuse log (no RLS — system-wide)."""

    __tablename__ = "signup_attempt_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email_canonical: Mapped[str | None] = mapped_column(String(320), nullable=True)
    client_ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    route: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
