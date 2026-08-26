from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.domain.api_key_record import ApiKeyRecordModel


class ApiKeyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: ApiKeyRecordModel) -> ApiKeyRecordModel:
        self._session.add(record)
        self._session.flush()
        self._session.refresh(record)
        return record

    def get_by_key_id(self, key_id: str) -> ApiKeyRecordModel | None:
        stmt = select(ApiKeyRecordModel).where(ApiKeyRecordModel.key_id == key_id)
        return self._session.scalars(stmt).first()

    def get_by_key_id_for_update(self, key_id: str) -> ApiKeyRecordModel | None:
        """Lock one API-key row until transaction completion."""
        stmt = select(ApiKeyRecordModel).where(ApiKeyRecordModel.key_id == key_id).with_for_update()
        return self._session.scalars(stmt).first()

    def revoke(self, record: ApiKeyRecordModel) -> ApiKeyRecordModel:
        now = datetime.now(UTC)
        record.revoked = True
        record.revoked_at = now
        record.updated_at = now
        self._session.flush()
        return record

    def count_active_for_tenant(self, *, tenant_id: str) -> int:
        """Return the count of non-revoked API keys for the given tenant."""
        stmt = (
            select(func.count())
            .select_from(ApiKeyRecordModel)
            .where(
                ApiKeyRecordModel.tenant_id == tenant_id,
                ApiKeyRecordModel.revoked.is_(False),
            )
        )
        return self._session.scalar(stmt) or 0
