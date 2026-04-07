from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.queue.base import QueueAdapter, QueueMessage
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.runtime.transitions import transition_task
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
        tasks = list(self._session.scalars(stmt))
        return [
            {
                "task_id": str(task.id),
                "mission_id": str(task.mission_id),
                "status": task.status,
            }
            for task in tasks
        ]

    def retry_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID) -> dict[str, str]:
        task = self._session.get(ExecutionTask, task_id)
        if task is None or task.tenant_id != tenant_id:
            raise ValueError("task not found for tenant")
        if task.status != ExecutionTaskState.DEAD_LETTERED.value:
            raise ValueError("task is not dead-lettered")

        previous_state = task.status
        transition_task(task, ExecutionTaskState.QUEUED)
        self._session.flush()

        enqueue_result = self._queue.enqueue_task(
            QueueMessage(
                tenant_id=tenant_id,
                task_id=task.id,
                mission_id=task.mission_id,
                fleet_id=task.fleet_id,
                branch_id=task.branch_id,
                payload=task.metadata_json,
                enqueued_at=datetime.now(UTC),
            )
        )
        if not enqueue_result.ok:
            task.status = previous_state
            self._session.flush()
            raise ValueError(enqueue_result.reason or "queue enqueue failed")

        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="operations",
                action="retry_dead_letter",
                actor="operations_service",
                details=f"Retried dead-letter task {task.id}",
                payload_json={"task_id": str(task.id)},
            )
        )
        self._session.flush()
        return {"task_id": str(task.id), "status": task.status}

    def trigger_recovery(self) -> RecoverySummary:
        return self._maintainer.recover_expired_leases()
