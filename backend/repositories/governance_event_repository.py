from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.governance_event import GovernanceEvent


class GovernanceEventRepository:
    """Append-only governance event storage."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: GovernanceEvent) -> GovernanceEvent:
        self._session.add(event)
        self._session.flush()
        self._session.refresh(event)
        return event

    def list_for_mission(self, mission_id: uuid.UUID) -> list[GovernanceEvent]:
        stmt = select(GovernanceEvent).where(GovernanceEvent.mission_id == mission_id)
        return list(self._session.scalars(stmt))
