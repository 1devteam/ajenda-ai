from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.domain.tenant_internal_record import TenantInternalRecord
from backend.domain.business_profile_projection import PROFILE_ACCOUNT_RECORD_ID, PROFILE_CONTACT_RECORD_ID
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.services.tools.record_types import SUPPORTED_RECORD_TYPES


class TenantInternalRecordRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def search_records(
        self,
        *,
        tenant_id: str,
        record_type: str,
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        self._validate_record_type(record_type)
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")

        stmt = select(TenantInternalRecord).where(
            TenantInternalRecord.tenant_id == tenant_id,
            TenantInternalRecord.record_type == record_type,
            TenantInternalRecord.deleted.is_(False),
        )
        normalized_query = query.lower().strip()
        if normalized_query:
            pattern = f"%{normalized_query}%"
            stmt = stmt.where(
                or_(
                    TenantInternalRecord.search_text.ilike(pattern),
                    TenantInternalRecord.record_id.ilike(pattern),
                )
            )
        rows = list(self._session.scalars(stmt.order_by(TenantInternalRecord.updated_at.desc()).limit(limit * 3)).all())
        matches: list[dict[str, Any]] = []
        filters = filters or {}
        for row in rows:
            record = dict(row.data_json)
            record.setdefault("id", row.record_id)
            if any(record.get(key) != value for key, value in filters.items()):
                continue
            matches.append(record)
            if len(matches) >= limit:
                break
        return matches

    def read_record(self, *, tenant_id: str, record_type: str, record_id: str) -> dict[str, Any] | None:
        self._validate_record_type(record_type)
        stmt = select(TenantInternalRecord).where(
            TenantInternalRecord.tenant_id == tenant_id,
            TenantInternalRecord.record_type == record_type,
            TenantInternalRecord.record_id == record_id,
            TenantInternalRecord.deleted.is_(False),
        )
        row = self._session.scalars(stmt).first()
        if row is None:
            return None
        record = dict(row.data_json)
        record.setdefault("id", row.record_id)
        return record

    def write_record(
        self,
        *,
        tenant_id: str,
        record_type: str,
        record_id: str | None,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_record_type(record_type)
        tenant_rows = self._session.scalar(
            select(func.count())
            .select_from(TenantInternalRecord)
            .where(
                TenantInternalRecord.tenant_id == tenant_id,
                TenantInternalRecord.record_type == record_type,
                TenantInternalRecord.deleted.is_(False),
            )
        )
        final_id = record_id or f"{record_type}-{int(tenant_rows or 0) + 1}"
        record = {**dict(data), "id": final_id}
        search_text = " ".join(str(value).lower() for value in record.values())

        stmt = select(TenantInternalRecord).where(
            TenantInternalRecord.tenant_id == tenant_id,
            TenantInternalRecord.record_type == record_type,
            TenantInternalRecord.record_id == final_id,
        )
        existing = self._session.scalars(stmt).first()
        now = datetime.now(UTC)
        if existing is None:
            row = TenantInternalRecord(
                id=f"tir-{uuid.uuid4()}",
                tenant_id=tenant_id,
                record_type=record_type,
                record_id=final_id,
                data_json=record,
                search_text=search_text,
                deleted=False,
                created_at=now,
                updated_at=now,
            )
            self._session.add(row)
        else:
            existing.data_json = record
            existing.search_text = search_text
            existing.deleted = False
            existing.updated_at = now
        self._session.flush()
        return dict(record)

    def seed_defaults_if_empty(self, *, tenant_id: str) -> None:
        count = self._session.scalar(
            select(func.count())
            .select_from(TenantInternalRecord)
            .where(TenantInternalRecord.tenant_id == tenant_id, TenantInternalRecord.deleted.is_(False))
        )
        if count:
            return
        if self._should_skip_demo_seed(tenant_id=tenant_id):
            return
        from backend.services.ajenda_demo_fixtures import seed_ajenda_live_demo

        seed_ajenda_live_demo(session=self._session, tenant_id=tenant_id)

    def _should_skip_demo_seed(self, *, tenant_id: str) -> bool:
        for record_id in (PROFILE_ACCOUNT_RECORD_ID, PROFILE_CONTACT_RECORD_ID):
            existing = self._session.scalars(
                select(TenantInternalRecord).where(
                    TenantInternalRecord.tenant_id == tenant_id,
                    TenantInternalRecord.record_id == record_id,
                    TenantInternalRecord.deleted.is_(False),
                )
            ).first()
            if existing is not None:
                return True
        profile = BusinessProfileRepository(self._session).get_active_profile_for_tenant(tenant_id=tenant_id)
        if profile is not None and isinstance(profile.approved_facts, dict) and profile.approved_facts:
            return True
        return False

    @staticmethod
    def _validate_record_type(record_type: str) -> None:
        if record_type not in SUPPORTED_RECORD_TYPES:
            raise ValueError(f"unsupported record_type: {record_type}")
