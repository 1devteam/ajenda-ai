from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.services.execution_coordinator import ExecutionCoordinator


@dataclass(frozen=True, slots=True)
class MissionTaskDenial:
    task_id: uuid.UUID
    state: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class MissionQueueSummary:
    queued_task_ids: list[uuid.UUID]
    pending_review_task_ids: list[uuid.UUID]
    denied_tasks: list[MissionTaskDenial]


class MissionExecutor:
    """Execution behavior only; coordination remains external."""

    def __init__(self, session: Session, coordinator: ExecutionCoordinator) -> None:
        self._session = session
        self._coordinator = coordinator
        self._tasks = ExecutionTaskRepository(session)

    def queue_all_planned_tasks(self, *, tenant_id: str, mission_id: uuid.UUID) -> MissionQueueSummary:
        queued: list[uuid.UUID] = []
        pending_review: list[uuid.UUID] = []
        denied: list[MissionTaskDenial] = []

        for task in self._tasks.list_for_mission(mission_id):
            if task.tenant_id != tenant_id or task.status != ExecutionTaskState.PLANNED.value:
                continue
            result = self._coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)
            if result.ok:
                queued.append(task.id)
                continue
            if result.state == "pending_review":
                pending_review.append(task.id)
                continue
            denied.append(
                MissionTaskDenial(
                    task_id=task.id,
                    state=result.state,
                    reason=result.reason,
                )
            )

        return MissionQueueSummary(
            queued_task_ids=queued,
            pending_review_task_ids=pending_review,
            denied_tasks=denied,
        )
