from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.services.execution_coordinator import ExecutionCoordinator


class MissionExecutor:
    """Execution behavior only; coordination remains external."""

    def __init__(self, session: Session, coordinator: ExecutionCoordinator) -> None:
        self._session = session
        self._coordinator = coordinator
        self._tasks = ExecutionTaskRepository(session)

    def queue_all_planned_tasks(self, *, tenant_id: str, mission_id: uuid.UUID) -> list[uuid.UUID]:
        queued: list[uuid.UUID] = []
        for task in self._tasks.list_for_mission(mission_id):
            if task.tenant_id != tenant_id:
                continue
            result = self._coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)
            if result.ok:
                queued.append(task.id)
        return queued
