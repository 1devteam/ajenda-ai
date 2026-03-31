from __future__ import annotations

import uuid

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

    def list_by_tenant(self, tenant_id: str) -> list[Mission]:
        stmt = select(Mission).where(Mission.tenant_id == tenant_id).order_by(Mission.created_at.asc())
        return list(self._session.scalars(stmt))
