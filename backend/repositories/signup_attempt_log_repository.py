"""SignupAttemptLog repository — abuse observability data access."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.domain.signup_attempt_log import SignupAttemptLog


class SignupAttemptLogRepository:
    """Append-only access to signup abuse logs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        email_canonical: str | None,
        client_ip_hash: str,
        route: str,
        outcome: str,
    ) -> SignupAttemptLog:
        entry = SignupAttemptLog(
            id=uuid.uuid4(),
            email_canonical=email_canonical,
            client_ip_hash=client_ip_hash,
            route=route,
            outcome=outcome,
        )
        self._session.add(entry)
        return entry

    def count_for_email(
        self,
        *,
        email_canonical: str,
        route: str,
        since: datetime,
        outcomes: frozenset[str] | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(SignupAttemptLog)
            .where(
                SignupAttemptLog.email_canonical == email_canonical,
                SignupAttemptLog.route == route,
                SignupAttemptLog.created_at >= since,
            )
        )
        if outcomes is not None:
            stmt = stmt.where(SignupAttemptLog.outcome.in_(outcomes))
        return int(self._session.scalar(stmt) or 0)

    def count_for_ip(
        self,
        *,
        client_ip_hash: str,
        route: str,
        since: datetime,
        outcomes: frozenset[str] | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(SignupAttemptLog)
            .where(
                SignupAttemptLog.client_ip_hash == client_ip_hash,
                SignupAttemptLog.route == route,
                SignupAttemptLog.created_at >= since,
            )
        )
        if outcomes is not None:
            stmt = stmt.where(SignupAttemptLog.outcome.in_(outcomes))
        return int(self._session.scalar(stmt) or 0)

    @staticmethod
    def window_start(*, hours: int, now: datetime | None = None) -> datetime:
        current = now or datetime.now(UTC)
        return current - timedelta(hours=hours)
