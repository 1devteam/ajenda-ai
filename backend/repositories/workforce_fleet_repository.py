from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.workforce_fleet import WorkforceFleet


class WorkforceFleetRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, fleet: WorkforceFleet) -> WorkforceFleet:
        self._session.add(fleet)
        self._session.flush()
        self._session.refresh(fleet)
        return fleet

    def get(self, fleet_id: uuid.UUID) -> WorkforceFleet | None:
        return self._session.get(WorkforceFleet, fleet_id)

    def list_for_mission(self, mission_id: uuid.UUID) -> list[WorkforceFleet]:
        stmt = select(WorkforceFleet).where(WorkforceFleet.mission_id == mission_id)
        return list(self._session.scalars(stmt))
