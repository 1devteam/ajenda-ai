from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.governance_event import GovernanceEvent
from backend.queue.base import QueueAdapter, QueueMessage
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.governance_event_repository import GovernanceEventRepository
from backend.runtime.transitions import transition_task
from backend.services.runtime_governor import RuntimeGovernor, RuntimeMode


@dataclass(frozen=True, slots=True)
class CoordinationResult:
    ok: bool
    task_id: uuid.UUID
    state: str
    reason: str | None = None


class ExecutionCoordinator:
    def __init__(self, session: Session, queue: QueueAdapter) -> None:
        self._session = session
        self._queue = queue
        self._tasks = ExecutionTaskRepository(session)
        self._audit = AuditEventRepository(session)
        self._governance = GovernanceEventRepository(session)
        self._governor = RuntimeGovernor(session)

    def queue_task(self, *, tenant_id: str, task_id: uuid.UUID) -> CoordinationResult:
        task = self._require_task(task_id=task_id, tenant_id=tenant_id)
        decision = self._governor.evaluate()
        if decision.mode not in {RuntimeMode.NORMAL, RuntimeMode.RECOVERY}:
            self._emit_denial(task=task, tenant_id=tenant_id, reason=decision.reason)
            return CoordinationResult(ok=False, task_id=task.id, state=task.status, reason=decision.reason)

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
                enqueued_at=datetime.now(timezone.utc),
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
                category="execution_task",
                action="queued",
                actor="execution_coordinator",
                details=f"Task {task.id} queued for execution.",
                payload_json={"task_id": str(task.id)},
            )
        )
        self._session.flush()
        return CoordinationResult(ok=True, task_id=task.id, state=task.status)

    def mark_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID, reason: str) -> CoordinationResult:
        task = self._require_task(task_id=task_id, tenant_id=tenant_id)
        transition_task(task, ExecutionTaskState.DEAD_LETTERED)
        self._session.flush()

        move_result = self._queue.move_to_dead_letter(
            tenant_id=tenant_id,
            task_id=task.id,
            reason=reason,
        )
        if not move_result.ok:
            raise ValueError(move_result.reason or "move to dead letter failed")

        self._governance.append(
            GovernanceEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                event_type="dead_letter",
                actor="execution_coordinator",
                decision=reason,
                payload_json={"task_id": str(task.id)},
            )
        )
        self._session.flush()
        return CoordinationResult(ok=True, task_id=task.id, state=task.status)

    def _emit_denial(self, *, task: ExecutionTask, tenant_id: str, reason: str) -> None:
        self._governance.append(
            GovernanceEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                event_type="dispatch_denied",
                actor="runtime_governor",
                decision=reason,
                payload_json={"task_id": str(task.id)},
            )
        )
        self._session.flush()

    def _require_task(self, *, task_id: uuid.UUID, tenant_id: str) -> ExecutionTask:
        task = self._tasks.get(task_id)
        if task is None or task.tenant_id != tenant_id:
            raise ValueError("task not found for tenant")
        return task
