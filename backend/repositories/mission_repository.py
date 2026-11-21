from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.domain.enums import MissionState
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

    def get_reference_for_tenant(self, *, mission_id: uuid.UUID, tenant_id: str) -> Mission | None:
        """Read mission attribution through the tenant-scoped lookup."""
        return self.get_for_tenant(mission_id=mission_id, tenant_id=tenant_id)

    def lock_for_tenant(self, *, mission_id: uuid.UUID, tenant_id: str) -> Mission | None:
        """Return a tenant-owned mission while holding a row lock for mutation serialization."""
        stmt = select(Mission).where(Mission.id == mission_id, Mission.tenant_id == tenant_id).with_for_update()
        return self._session.scalar(stmt)

    def list_by_tenant(self, tenant_id: str, *, limit: int = 50) -> list[Mission]:
        stmt = (
            select(Mission)
            .where(Mission.tenant_id == tenant_id)
            .order_by(Mission.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
        return list(self._session.scalars(stmt))

    def count_by_tenant(self, tenant_id: str) -> int:
        """Return the complete tenant-scoped mission count, independent of page size."""
        stmt = select(func.count()).select_from(Mission).where(Mission.tenant_id == tenant_id)
        return int(self._session.scalar(stmt) or 0)

    def count_completed_by_tenant(self, tenant_id: str) -> int:
        """Return completed missions for one tenant using the canonical lifecycle state."""
        stmt = (
            select(func.count())
            .select_from(Mission)
            .where(Mission.tenant_id == tenant_id, Mission.status == MissionState.COMPLETED.value)
        )
        return int(self._session.scalar(stmt) or 0)
