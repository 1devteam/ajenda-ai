from __future__ import annotations

import uuid
from typing import cast

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
        return cast(ExecutionTask | None, self._session.get(ExecutionTask, task_id))

    def get_for_tenant(self, *, task_id: uuid.UUID, tenant_id: str) -> ExecutionTask | None:
        """Resolve a task without exposing the existence of another tenant's row."""

        stmt = select(ExecutionTask).where(
            ExecutionTask.id == task_id,
            ExecutionTask.tenant_id == tenant_id,
        )
        return self._session.scalar(stmt)

    def get_for_update(self, task_id: uuid.UUID) -> ExecutionTask | None:
        stmt = select(ExecutionTask).where(ExecutionTask.id == task_id).with_for_update()
        # Lightweight contract fakes may only implement ``Session.get``. The
        # production SQLAlchemy session always takes the locking scalar path;
        # this fallback keeps the repository boundary usable for those fakes
        # without weakening the real row-locking behavior.
        scalar = getattr(self._session, "scalar", None)
        if callable(scalar):
            return cast(ExecutionTask | None, scalar(stmt))
        return self._session.get(ExecutionTask, task_id)

    def list_for_mission(self, mission_id: uuid.UUID) -> list[ExecutionTask]:
        stmt = select(ExecutionTask).where(ExecutionTask.mission_id == mission_id)
        return list(self._session.scalars(stmt))

    def list_for_mission_for_tenant(
        self,
        *,
        mission_id: uuid.UUID,
        tenant_id: str,
    ) -> list[ExecutionTask]:
        """List mission tasks without relying on globally unique mission identity for tenancy."""

        stmt = (
            select(ExecutionTask)
            .where(
                ExecutionTask.mission_id == mission_id,
                ExecutionTask.tenant_id == tenant_id,
            )
            .order_by(ExecutionTask.created_at.asc(), ExecutionTask.id.asc())
        )
        return list(self._session.scalars(stmt))

    def list_pending_review_for_tenant(self, *, tenant_id: str, limit: int = 50) -> list[ExecutionTask]:
        stmt = (
            select(ExecutionTask)
            .where(
                ExecutionTask.tenant_id == tenant_id,
                ExecutionTask.status == ExecutionTaskState.PENDING_REVIEW.value,
                ExecutionTask.requires_human_review.is_(True),
            )
            .order_by(ExecutionTask.created_at.asc(), ExecutionTask.id.asc())
            .limit(limit)
        )
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
