from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.execution_task import ExecutionTask


class ExecutionTaskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, task: ExecutionTask) -> ExecutionTask:
        self._session.add(task)
        self._session.flush()
        self._session.refresh(task)
        return task

    def get(self, task_id: uuid.UUID) -> ExecutionTask | None:
        return self._session.get(ExecutionTask, task_id)

    def list_for_mission(self, mission_id: uuid.UUID) -> list[ExecutionTask]:
        stmt = select(ExecutionTask).where(ExecutionTask.mission_id == mission_id)
        return list(self._session.scalars(stmt))
