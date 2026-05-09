from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.domain.capability_adapter import CapabilityAdapter


class CapabilityAdapterRepository:
    """Persistence contract for declarative capability execution adapter records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, adapter: CapabilityAdapter) -> CapabilityAdapter:
        self._session.add(adapter)
        self._session.flush()
        self._session.refresh(adapter)
        return adapter

    def get_visible_for_tenant(self, *, adapter_id: uuid.UUID, tenant_id: str) -> CapabilityAdapter | None:
        stmt = select(CapabilityAdapter).where(
            CapabilityAdapter.id == adapter_id,
            or_(CapabilityAdapter.tenant_id == tenant_id, CapabilityAdapter.tenant_id.is_(None)),
        )
        return self._session.scalar(stmt)

    def list_visible_for_tenant(self, *, tenant_id: str) -> list[CapabilityAdapter]:
        stmt = (
            select(CapabilityAdapter)
            .where(or_(CapabilityAdapter.tenant_id == tenant_id, CapabilityAdapter.tenant_id.is_(None)))
            .order_by(
                CapabilityAdapter.tenant_id.is_not(None).asc(),
                CapabilityAdapter.name.asc(),
                CapabilityAdapter.version.asc(),
            )
        )
        return list(self._session.scalars(stmt))

    def get_conflict_for_scope(self, *, name: str, version: str, tenant_id: str | None) -> CapabilityAdapter | None:
        stmt = select(CapabilityAdapter).where(CapabilityAdapter.name == name, CapabilityAdapter.version == version)
        if tenant_id is None:
            stmt = stmt.where(CapabilityAdapter.tenant_id.is_(None))
        else:
            stmt = stmt.where(CapabilityAdapter.tenant_id == tenant_id)
        return self._session.scalar(stmt)

    def update(self, adapter: CapabilityAdapter) -> CapabilityAdapter:
        self._session.add(adapter)
        self._session.flush()
        self._session.refresh(adapter)
        return adapter
