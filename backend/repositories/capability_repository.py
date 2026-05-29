from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.domain.capability import Capability


class CapabilityRepository:
    """Persistence contract for declarative capability registry records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, capability: Capability) -> Capability:
        self._session.add(capability)
        self._session.flush()
        self._session.refresh(capability)
        return capability

    def get_visible_for_tenant(self, *, capability_id: uuid.UUID, tenant_id: str) -> Capability | None:
        stmt = select(Capability).where(
            Capability.id == capability_id,
            or_(Capability.tenant_id == tenant_id, Capability.tenant_id.is_(None)),
        )
        return self._session.scalar(stmt)

    def get_visible_by_name_version(self, *, name: str, version: str, tenant_id: str) -> Capability | None:
        stmt = (
            select(Capability)
            .where(
                Capability.name == name,
                Capability.version == version,
                or_(Capability.tenant_id == tenant_id, Capability.tenant_id.is_(None)),
            )
            .order_by(Capability.tenant_id.is_(None).asc())
        )
        return self._session.scalar(stmt)

    def list_visible_for_tenant(self, *, tenant_id: str) -> list[Capability]:
        stmt = (
            select(Capability)
            .where(or_(Capability.tenant_id == tenant_id, Capability.tenant_id.is_(None)))
            .order_by(Capability.tenant_id.is_not(None).asc(), Capability.name.asc(), Capability.version.asc())
        )
        return list(self._session.scalars(stmt))

    def get_conflict_for_scope(self, *, name: str, version: str, tenant_id: str | None) -> Capability | None:
        stmt = select(Capability).where(Capability.name == name, Capability.version == version)
        if tenant_id is None:
            stmt = stmt.where(Capability.tenant_id.is_(None))
        else:
            stmt = stmt.where(Capability.tenant_id == tenant_id)
        return self._session.scalar(stmt)

    def update(self, capability: Capability) -> Capability:
        self._session.add(capability)
        self._session.flush()
        self._session.refresh(capability)
        return capability
