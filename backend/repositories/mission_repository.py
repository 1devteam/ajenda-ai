from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.mission import Mission


class MissionRepository:
    """Persistence contract for canonical mission records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, mission: Mission) -> Mission:
        self._session.add(mission)
        self._session.flush()
        self._session.refresh(mission)
        return mission

    def get(self, mission_id: uuid.UUID) -> Mission | None:
        return self._session.get(Mission, mission_id)

    def update_metadata(self, *, mission: Mission, metadata_json: dict[str, Any]) -> Mission:
        mission.metadata_json = metadata_json
        self._session.add(mission)
        self._session.flush()
        self._session.refresh(mission)
        return mission

    def get_for_tenant(self, *, mission_id: uuid.UUID, tenant_id: str) -> Mission | None:
        stmt = select(Mission).where(Mission.id == mission_id, Mission.tenant_id == tenant_id)
        return self._session.scalar(stmt)

    def get_for_tenant_locked(self, *, mission_id: uuid.UUID, tenant_id: str) -> Mission | None:
        stmt = select(Mission).where(Mission.id == mission_id, Mission.tenant_id == tenant_id).with_for_update()
        return self._session.scalar(stmt)

    def list_by_tenant(self, tenant_id: str) -> list[Mission]:
        stmt = select(Mission).where(Mission.tenant_id == tenant_id).order_by(Mission.created_at.asc())
        return list(self._session.scalars(stmt))
