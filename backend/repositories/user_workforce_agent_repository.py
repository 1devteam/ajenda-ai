from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.user_workforce_agent import UserWorkforceAgent


class UserWorkforceAgentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, agent: UserWorkforceAgent) -> UserWorkforceAgent:
        self._session.add(agent)
        self._session.flush()
        self._session.refresh(agent)
        return agent

    def get(self, agent_id: uuid.UUID) -> UserWorkforceAgent | None:
        return self._session.get(UserWorkforceAgent, agent_id)

    def list_for_fleet(self, fleet_id: uuid.UUID) -> list[UserWorkforceAgent]:
        stmt = select(UserWorkforceAgent).where(UserWorkforceAgent.fleet_id == fleet_id)
        return list(self._session.scalars(stmt))
