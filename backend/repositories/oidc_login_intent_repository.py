"""OidcLoginIntentRepository — PKCE login intent persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.oidc_login_intent import OidcLoginIntent


class OidcLoginIntentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        code_challenge: str,
        redirect_uri: str,
        nonce: str,
        client_ip_hash: str,
        expires_at: datetime,
    ) -> OidcLoginIntent:
        intent = OidcLoginIntent(
            id=uuid.uuid4(),
            code_challenge=code_challenge,
            redirect_uri=redirect_uri,
            nonce=nonce,
            client_ip_hash=client_ip_hash,
            expires_at=expires_at,
        )
        self._session.add(intent)
        return intent

    def get(self, intent_id: uuid.UUID) -> OidcLoginIntent | None:
        return self._session.get(OidcLoginIntent, intent_id)

    def consume(self, intent: OidcLoginIntent, *, consumed_at: datetime | None = None) -> OidcLoginIntent:
        intent.consumed_at = consumed_at or datetime.now(tz=UTC)
        return intent

    def delete_expired(self, *, before: datetime) -> int:
        stmt = select(OidcLoginIntent).where(OidcLoginIntent.expires_at < before)
        rows = list(self._session.scalars(stmt).all())
        for row in rows:
            self._session.delete(row)
        return len(rows)
