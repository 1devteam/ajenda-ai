from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.queue.base import QueueAdapter, QueueMessage, QueueOperationResult
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

        previous_state = task.status
        queue_entries = [
            entry for entry in self._queue.list_dead_letter(tenant_id=tenant_id) if entry.task_id == task.id
        ]
        if queue_entries:
            enqueue_result = self._queue.retry_dead_letter(tenant_id=tenant_id, task_id=task.id)
        else:
            enqueue_result = self._recover_existing_queue_payload_or_enqueue_from_db(tenant_id=tenant_id, task=task)
        if not enqueue_result.ok:
            raise ValueError(enqueue_result.reason or "queue enqueue failed")

        try:
            transition_task(task, ExecutionTaskState.QUEUED)
        except ValueError:
            task.status = previous_state
            self._session.flush()
            raise
        self._session.flush()

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

    def _recover_existing_queue_payload_or_enqueue_from_db(
        self,
        *,
        tenant_id: str,
        task: ExecutionTask,
    ) -> QueueOperationResult:
        recovery_result = self._queue.recover_task_for_retry(
            tenant_id=tenant_id,
            task_id=task.id,
            worker_id="operations_service_retry",
        )
        if recovery_result.ok:
            return recovery_result
        if recovery_result.reason != "task not found in processing or pending queue":
            return recovery_result
        return self._queue.enqueue_task(self._queue_message_for_task(tenant_id=tenant_id, task=task))

    @staticmethod
    def _queue_message_for_task(*, tenant_id: str, task: ExecutionTask) -> QueueMessage:
        return QueueMessage(
            tenant_id=tenant_id,
            task_id=task.id,
            mission_id=task.mission_id,
            fleet_id=task.fleet_id,
            branch_id=task.branch_id,
            payload=task.metadata_json,
            enqueued_at=datetime.now(UTC),
        )
