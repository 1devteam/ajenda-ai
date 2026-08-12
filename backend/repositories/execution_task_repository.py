from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.runtime.transitions import transition_task


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

    def get_for_tenant(self, *, task_id: uuid.UUID, tenant_id: str) -> ExecutionTask | None:
        """Resolve a task without exposing the existence of another tenant's row."""

        stmt = select(ExecutionTask).where(
            ExecutionTask.id == task_id,
            ExecutionTask.tenant_id == tenant_id,
        )
        return self._session.scalar(stmt)

    def get_for_update(self, task_id: uuid.UUID) -> ExecutionTask | None:
        stmt = select(ExecutionTask).where(ExecutionTask.id == task_id).with_for_update()
        return self._session.scalar(stmt)

    def list_for_mission(self, mission_id: uuid.UUID) -> list[ExecutionTask]:
        stmt = select(ExecutionTask).where(ExecutionTask.mission_id == mission_id)
        return list(self._session.scalars(stmt))

    def cancel_planned_by_ids_for_mission(
        self, *, tenant_id: str, mission_id: uuid.UUID, task_ids: list[uuid.UUID]
    ) -> list[ExecutionTask]:
        """Cancel tenant-owned planned tasks by ID for a mission supersession."""
        if not task_ids:
            return []
        stmt = select(ExecutionTask).where(
            ExecutionTask.id.in_(task_ids),
            ExecutionTask.tenant_id == tenant_id,
            ExecutionTask.mission_id == mission_id,
            ExecutionTask.status == ExecutionTaskState.PLANNED.value,
        )
        tasks = list(self._session.scalars(stmt))
        for task in tasks:
            transition_task(task, ExecutionTaskState.CANCELLED)
            self._session.add(task)
        self._session.flush()
        for task in tasks:
            self._session.refresh(task)
        return tasks
