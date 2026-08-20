from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.queue.base import QueueAdapter
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.runtime_maintainer import RecoverySummary, RuntimeMaintainer


class OperationsService:
    def __init__(self, session: Session, queue: QueueAdapter) -> None:
        self._session = session
        self._queue = queue
        self._audit = AuditEventRepository(session)
        self._maintainer = RuntimeMaintainer(session, queue)

    def inspect_dead_letter(self, *, tenant_id: str) -> list[dict[str, str]]:
        stmt = select(ExecutionTask).where(
            ExecutionTask.tenant_id == tenant_id,
            ExecutionTask.status == ExecutionTaskState.DEAD_LETTERED.value,
        )
        rows: dict[str, dict[str, str]] = {}
        for task in self._session.scalars(stmt):
            rows[str(task.id)] = {
                "task_id": str(task.id),
                "mission_id": str(task.mission_id),
                "status": task.status,
            }

        for entry in self._queue.list_dead_letter(tenant_id=tenant_id):
            if entry.task_id is None:
                rows[f"corrupt:{len(rows)}"] = {
                    "task_id": "",
                    "mission_id": "",
                    "status": "corrupt_dead_letter",
                }
                continue
            queue_task = self._session.get(ExecutionTask, entry.task_id)
            if queue_task is None or queue_task.tenant_id != tenant_id:
                continue
            rows.setdefault(
                str(queue_task.id),
                {
                    "task_id": str(queue_task.id),
                    "mission_id": str(queue_task.mission_id),
                    "status": queue_task.status,
                },
            )
        return list(rows.values())

    def retry_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID) -> dict[str, str]:
        task = self._session.get(ExecutionTask, task_id)
        if task is None or task.tenant_id != tenant_id:
            raise ValueError("task not found for tenant")
        if task.status not in {ExecutionTaskState.DEAD_LETTERED.value, ExecutionTaskState.FAILED.value}:
            raise ValueError("task is not dead-lettered or failed")

        result = ExecutionCoordinator(self._session, self._queue, audit_repository=self._audit).retry_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )
        return {"task_id": str(task.id), "status": result.state}

    def trigger_recovery(self) -> RecoverySummary:
        return self._maintainer.recover_expired_leases()
