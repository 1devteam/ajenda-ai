from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

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
from backend.services.policy_guardian import PolicyGuardian
from backend.services.runtime_governor import RuntimeGovernor

logger = logging.getLogger("ajenda.execution_coordinator")


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
        self._policy = PolicyGuardian(session)

    def queue_task(self, *, tenant_id: str, task_id: uuid.UUID) -> CoordinationResult:
        task = self._require_task(task_id=task_id, tenant_id=tenant_id)

        decision = self._governor.evaluate()
        logger.info(
            "governance_decision",
            extra={
                "task_id": str(task_id),
                "mode": decision.mode,
                "execution_allowed": decision.execution_allowed,
            },
        )

        if not decision.execution_allowed:
            self._emit_denial(task=task, tenant_id=tenant_id, reason=decision.reason)
            return CoordinationResult(
                ok=False,
                task_id=task.id,
                state=task.status,
                reason=decision.reason,
            )

        policy_decision = self._policy.evaluate_task(task)
        logger.info(
            "policy_decision",
            extra={
                "task_id": str(task_id),
                "allowed": policy_decision.allowed,
                "reason": policy_decision.reason,
            },
        )

        if not policy_decision.allowed:
            transition_task(task, ExecutionTaskState.PENDING_REVIEW)
            task.requires_human_review = True
            self._session.flush()

            self._governance.append(
                GovernanceEvent(
                    tenant_id=tenant_id,
                    mission_id=task.mission_id,
                    event_type="compliance_review_required",
                    actor="policy_guardian",
                    decision=policy_decision.reason,
                    payload_json={
                        "task_id": str(task.id),
                        "compliance_category": task.compliance_category,
                        "jurisdiction": task.jurisdiction,
                        "reason": policy_decision.reason,
                    },
                )
            )
            self._audit.append(
                AuditEvent(
                    tenant_id=tenant_id,
                    mission_id=task.mission_id,
                    category="compliance",
                    action="task_pending_review",
                    actor="policy_guardian",
                    details=f"Task {task.id} requires human review before execution. Reason: {policy_decision.reason}",
                    payload_json={
                        "task_id": str(task.id),
                        "reason": policy_decision.reason,
                    },
                )
            )
            self._session.flush()
            return CoordinationResult(
                ok=False,
                task_id=task.id,
                state=task.status,
                reason=policy_decision.reason,
            )

        previous_state = task.status
        transition_task(task, ExecutionTaskState.QUEUED)
        self._session.flush()
        self._enqueue_or_restore(task=task, tenant_id=tenant_id, previous_state=previous_state)

        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="execution_task",
                action="queued",
                actor="execution_coordinator",
                details=f"Task {task.id} queued for execution.",
                payload_json={"task_id": str(task.id), "mode": decision.mode},
            )
        )
        self._session.flush()
        return CoordinationResult(ok=True, task_id=task.id, state=task.status)

    def approve_review_and_queue(self, *, tenant_id: str, task_id: uuid.UUID, actor: str) -> CoordinationResult:
        """Approve a pending-review task and enqueue the runtime payload."""
        task = self._require_task_for_update(task_id=task_id, tenant_id=tenant_id)
        if task.status != ExecutionTaskState.PENDING_REVIEW.value:
            raise ValueError(f"expected status 'pending_review', got '{task.status}'")

        previous_state = task.status
        transition_task(task, ExecutionTaskState.QUEUED)
        self._session.flush()
        self._enqueue_or_restore(task=task, tenant_id=tenant_id, previous_state=previous_state)

        self._governance.append(
            GovernanceEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                event_type="human_review_approved",
                actor=actor,
                decision="approved",
                payload_json={"task_id": str(task.id), "previous_status": previous_state},
            )
        )
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="compliance",
                action="task_review_approved",
                actor=actor,
                details=f"Task {task.id} approved by human review and queued for execution.",
                payload_json={"task_id": str(task.id), "previous_status": previous_state},
            )
        )
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="execution_task",
                action="queued",
                actor="execution_coordinator",
                details=f"Task {task.id} queued for execution after human review approval.",
                payload_json={"task_id": str(task.id), "approved_by": actor},
            )
        )
        self._session.flush()
        return CoordinationResult(ok=True, task_id=task.id, state=task.status)

    def mark_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID, reason: str) -> CoordinationResult:
        task = self._require_task(task_id=task_id, tenant_id=tenant_id)
        previous_state = task.status
        transition_task(task, ExecutionTaskState.DEAD_LETTERED)
        self._session.flush()

        move_result = self._queue.move_to_dead_letter(
            tenant_id=tenant_id,
            task_id=task.id,
            reason=reason,
        )
        if not move_result.ok:
            logger.error(
                "dead_letter_queue_move_failed_rolling_back",
                extra={"task_id": str(task_id), "reason": move_result.reason},
            )
            task.status = previous_state
            self._session.flush()
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

    def _enqueue_or_restore(self, *, task: ExecutionTask, tenant_id: str, previous_state: str) -> None:
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
        if enqueue_result.ok:
            return

        logger.error(
            "queue_enqueue_failed_rolling_back",
            extra={"task_id": str(task.id), "reason": enqueue_result.reason},
        )
        task.status = previous_state
        self._session.flush()
        raise ValueError(enqueue_result.reason or "queue enqueue failed")

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

    def _require_task_for_update(self, *, task_id: uuid.UUID, tenant_id: str) -> ExecutionTask:
        task = self._tasks.get_for_update(task_id)
        if task is None or task.tenant_id != tenant_id:
            raise ValueError("task not found for tenant")
        return task
