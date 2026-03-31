from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.user_workforce_agent_repository import UserWorkforceAgentRepository


class WorkforceCoordinator:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._tasks = ExecutionTaskRepository(session)
        self._agents = UserWorkforceAgentRepository(session)

    def assign_task_to_agent(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> None:
        task = self._tasks.get(task_id)
        agent = self._agents.get(agent_id)
        if task is None or agent is None:
            raise ValueError("task or agent not found")
        if task.tenant_id != tenant_id or agent.tenant_id != tenant_id:
            raise ValueError("cross-tenant assignment forbidden")
        task.assigned_agent_id = agent.id
        self._session.flush()
