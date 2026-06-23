"""CustomerAuthSessionRepository — revocable human session storage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.customer_auth_session import CustomerAuthSession


class CustomerAuthSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        member_id: uuid.UUID,
        tenant_id: uuid.UUID,
        access_jti: str,
        refresh_token_hash: str,
        expires_at: datetime,
        refresh_expires_at: datetime,
        client_ip_hash: str | None = None,
    ) -> CustomerAuthSession:
        record = CustomerAuthSession(
            id=uuid.uuid4(),
            member_id=member_id,
            tenant_id=tenant_id,
            access_jti=access_jti,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            refresh_expires_at=refresh_expires_at,
            client_ip_hash=client_ip_hash,
        )
        self._session.add(record)
        return record

    def get_by_access_jti(self, access_jti: str) -> CustomerAuthSession | None:
        stmt = select(CustomerAuthSession).where(CustomerAuthSession.access_jti == access_jti)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_refresh_token_hash(self, refresh_token_hash: str) -> CustomerAuthSession | None:
        stmt = select(CustomerAuthSession).where(CustomerAuthSession.refresh_token_hash == refresh_token_hash)
        return self._session.execute(stmt).scalar_one_or_none()

    def revoke(self, record: CustomerAuthSession, *, revoked_at: datetime | None = None) -> CustomerAuthSession:
        record.revoked_at = revoked_at or datetime.now(tz=UTC)
        return record
