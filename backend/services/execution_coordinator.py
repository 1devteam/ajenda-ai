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
from backend.domain.mission import MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY
from backend.queue.base import QueueAdapter, QueueMessage
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.governance_event_repository import GovernanceEventRepository
from backend.repositories.mission_repository import MissionRepository
from backend.runtime.transitions import transition_task
from backend.services.mission_bridge.queue_admission import record_reviewed_task_admission
from backend.services.policy_guardian import PolicyGuardian
from backend.services.runtime_governor import RuntimeGovernor
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.mission_input_binding import (
    DependencyNotReadyError,
    InputBindingError,
    apply_input_bindings,
)
from backend.services.tools.schemas import ToolInvocation, side_effect_authorized, tool_invocation_sha256

logger = logging.getLogger("ajenda.execution_coordinator")


@dataclass(frozen=True, slots=True)
class CoordinationResult:
    ok: bool
    task_id: uuid.UUID
    state: str
    reason: str | None = None


class ExecutionCoordinator:
    def __init__(
        self,
        session: Session,
        queue: QueueAdapter,
        *,
        audit_repository: AuditEventRepository | None = None,
    ) -> None:
        self._session = session
        self._queue = queue
        self._tasks = ExecutionTaskRepository(session)
        self._audit = audit_repository or AuditEventRepository(session)
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

        if self._requires_unapproved_side_effect_review(task):
            self._place_in_review(
                task=task,
                tenant_id=tenant_id,
                reason="side-effecting action requires independent human approval",
            )
            return CoordinationResult(
                ok=False,
                task_id=task.id,
                state=task.status,
                reason="side-effecting action requires independent human approval",
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
            self._place_in_review(task=task, tenant_id=tenant_id, reason=policy_decision.reason)
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

    @staticmethod
    def _requires_unapproved_side_effect_review(task: ExecutionTask) -> bool:
        metadata = task.metadata_json or {}
        raw_invocation = metadata.get("tool_invocation")
        if not isinstance(raw_invocation, dict):
            return False
        try:
            invocation = ToolInvocation.model_validate(raw_invocation)
            action = get_default_action_registry().get(invocation.action)
        except (TypeError, ValueError):
            return False
        return action.side_effect_for(invocation).has_side_effect and not side_effect_authorized(
            metadata,
            action.name,
            tenant_id=task.tenant_id,
            task_id=task.id,
        )

    def _place_in_review(self, *, task: ExecutionTask, tenant_id: str, reason: str) -> None:
        transition_task(task, ExecutionTaskState.PENDING_REVIEW)
        task.requires_human_review = True
        metadata = dict(task.metadata_json or {})
        if metadata.get("social_publication_state") == "draft":
            metadata["social_publication_state"] = "reviewed"
            task.metadata_json = metadata
        self._session.flush()
        self._governance.append(
            GovernanceEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                event_type="compliance_review_required",
                actor="policy_guardian",
                decision=reason,
                payload_json={
                    "task_id": str(task.id),
                    "compliance_category": task.compliance_category,
                    "jurisdiction": task.jurisdiction,
                    "reason": reason,
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
                details=f"Task {task.id} requires human review before execution. Reason: {reason}",
                payload_json={"task_id": str(task.id), "reason": reason},
            )
        )
        self._session.flush()

    def approve_review_and_queue(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        actor: str,
        approval_expires_at: datetime | None = None,
    ) -> CoordinationResult:
        """Approve a pending-review task and enqueue the runtime payload."""
        task = self._require_task_for_update(task_id=task_id, tenant_id=tenant_id)
        if task.status != ExecutionTaskState.PENDING_REVIEW.value:
            raise ValueError(f"expected status 'pending_review', got '{task.status}'")

        metadata = dict(task.metadata_json or {})
        invocation = metadata.get("tool_invocation")
        grant_payload: dict[str, object] | None = None
        if isinstance(invocation, dict):
            action_name = invocation.get("action")
            if not isinstance(action_name, str) or not action_name.strip():
                raise ValueError("pending-review tool task has no valid action to approve")
            try:
                parsed_invocation = ToolInvocation.model_validate(invocation)
                action = get_default_action_registry().get(parsed_invocation.action)
            except (TypeError, ValueError) as exc:
                raise ValueError("pending-review tool task has no valid action to approve") from exc
            constraints = dict(metadata.get("execution_constraints") or {})
            if action.side_effect_for(parsed_invocation).has_side_effect:
                parsed_invocation, binding_audit = self._bind_side_effect_invocation_for_approval(
                    task=task,
                    metadata=metadata,
                    invocation=parsed_invocation,
                )
                metadata["tool_invocation"] = parsed_invocation.model_dump(mode="json")
                if binding_audit is not None:
                    metadata["input_binding_audit"] = binding_audit
                approved_at = datetime.now(UTC)
                if approval_expires_at is None or approval_expires_at.tzinfo is None:
                    raise ValueError("side-effect approval requires a timezone-aware expiry")
                if approval_expires_at <= approved_at:
                    raise ValueError("side-effect approval expiry must be in the future")
                grant_payload = {
                    "schema_version": 2,
                    "grant_id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "task_id": str(task.id),
                    "allowed_action": action.name,
                    "invocation_sha256": tool_invocation_sha256(parsed_invocation),
                    "reason": "human_review_approved",
                    "approved_by": actor,
                    "approved_at": approved_at.isoformat(),
                    "expires_at": approval_expires_at.isoformat(),
                    "revoked_at": None,
                }
                constraints["side_effect_authorization"] = grant_payload
            metadata["execution_constraints"] = constraints
            if parsed_invocation.action == "gtm.social_publish":
                metadata["social_publication_state"] = "authorized"
            task.metadata_json = metadata
        elif metadata.get("task_type") == "tool.invoke":
            raise ValueError("pending-review tool task has no valid action to approve")

        previous_state = task.status
        self._session.flush()
        admission = self.queue_task(tenant_id=tenant_id, task_id=task.id)
        if not admission.ok:
            raise ValueError(admission.reason or "reviewed task failed runtime admission")

        self._record_reviewed_queue_admission(task=task, tenant_id=tenant_id)

        self._governance.append(
            GovernanceEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                event_type="human_review_approved",
                actor=actor,
                decision="approved",
                payload_json={
                    "task_id": str(task.id),
                    "previous_status": previous_state,
                    "approval_grant": grant_payload,
                },
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
                payload_json={
                    "task_id": str(task.id),
                    "previous_status": previous_state,
                    "approval_grant": grant_payload,
                },
            )
        )
        self._session.flush()
        return CoordinationResult(ok=True, task_id=task.id, state=task.status)

    def _record_reviewed_queue_admission(self, *, task: ExecutionTask, tenant_id: str) -> None:
        """Persist the canonical receipt after the coordinator enqueues a review."""

        if task.mission_id is None:
            return
        mission = MissionRepository(self._session).lock_for_tenant(
            mission_id=task.mission_id,
            tenant_id=tenant_id,
        )
        if mission is None:
            raise ValueError("reviewed task mission is not owned by tenant")
        metadata = dict(mission.metadata_json or {})
        receipt = metadata.get(MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY)
        if not isinstance(receipt, dict):
            raise ValueError("mission runtime queue admission receipt is missing")
        metadata[MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY] = record_reviewed_task_admission(
            receipt,
            task_id=task.id,
            now=datetime.now(UTC).isoformat(),
        )
        reconciliation = metadata.get("runtime_reconciliation")
        if isinstance(reconciliation, dict) and reconciliation.get("reason") == "review_hold_without_active_tasks":
            metadata["runtime_reconciliation"] = {
                **reconciliation,
                "status": "aligned",
                "reason": "reviewed_task_admitted",
                "pending_review_task_count": 0,
                "reconciled_at": datetime.now(UTC).isoformat(),
            }
        MissionRepository(self._session).update_metadata(mission=mission, metadata_json=metadata)
        self._session.flush()

    def _bind_side_effect_invocation_for_approval(
        self,
        *,
        task: ExecutionTask,
        metadata: dict[str, object],
        invocation: ToolInvocation,
    ) -> tuple[ToolInvocation, dict[str, object] | None]:
        """Finalize graph-bound inputs before issuing a payload-bound grant.

        Dependency-produced values are part of the authorized payload. Approving
        the composition seed and binding later would correctly invalidate the V2
        invocation hash at worker promotion. The coordinator is the grant owner,
        so it binds from tenant-scoped durable sibling outputs before hashing.
        """

        raw_dependencies = metadata.get("dependency_keys")
        raw_bindings = metadata.get("input_bindings")
        has_dependencies = isinstance(raw_dependencies, list) and bool(raw_dependencies)
        has_bindings = isinstance(raw_bindings, list) and bool(raw_bindings)
        if task.mission_id is None or (not has_dependencies and not has_bindings):
            return invocation, None

        mission_tasks = self._tasks.list_for_mission_for_tenant(
            mission_id=task.mission_id,
            tenant_id=task.tenant_id,
        )
        try:
            bound_input, audit = apply_input_bindings(
                tool_input=invocation.input,
                task=task,
                mission_tasks=mission_tasks,
            )
        except (DependencyNotReadyError, InputBindingError) as exc:
            raise ValueError(f"side-effect approval input binding failed: {exc}") from exc

        rebound = invocation.model_copy(update={"input": bound_input})
        return rebound, audit

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

    def retry_task(self, *, tenant_id: str, task_id: uuid.UUID) -> CoordinationResult:
        """Re-admit failed/dead-lettered work through governor, policy, review, and queue authority."""
        task = self._require_task_for_update(task_id=task_id, tenant_id=tenant_id)
        if task.status not in {ExecutionTaskState.DEAD_LETTERED.value, ExecutionTaskState.FAILED.value}:
            raise ValueError("task is not dead-lettered or failed")

        governor = self._governor.evaluate()
        if not governor.execution_allowed:
            self._emit_denial(task=task, tenant_id=tenant_id, reason=governor.reason)
            return CoordinationResult(False, task.id, task.status, governor.reason)
        if self._requires_unapproved_side_effect_review(task):
            self._place_in_review(
                task=task,
                tenant_id=tenant_id,
                reason="side-effecting retry requires a current independent human approval",
            )
            return CoordinationResult(
                False,
                task.id,
                task.status,
                "side-effecting retry requires a current independent human approval",
            )
        policy = self._policy.evaluate_task(task)
        if not policy.allowed:
            self._place_in_review(task=task, tenant_id=tenant_id, reason=policy.reason)
            return CoordinationResult(False, task.id, task.status, policy.reason)

        previous_state = task.status
        transition_task(task, ExecutionTaskState.QUEUED)
        self._session.flush()
        dead_letter_entries = [
            entry for entry in self._queue.list_dead_letter(tenant_id=tenant_id) if entry.task_id == task.id
        ]
        if dead_letter_entries:
            queue_result = self._queue.retry_dead_letter(tenant_id=tenant_id, task_id=task.id)
        else:
            queue_result = self._queue.recover_task_for_retry(
                tenant_id=tenant_id,
                task_id=task.id,
                worker_id="execution_coordinator_retry",
            )
            if queue_result.reason == "task not found in processing or pending queue":
                queue_result = self._queue.enqueue_task(
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
        if not queue_result.ok:
            task.status = previous_state
            self._session.flush()
            raise ValueError(queue_result.reason or "queue retry failed")

        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="operations",
                action="retry_dead_letter",
                actor="execution_coordinator",
                details=f"Re-admitted retry task {task.id} through runtime gates.",
                payload_json={"task_id": str(task.id), "previous_status": previous_state},
            )
        )
        self._session.flush()
        return CoordinationResult(True, task.id, task.status)

    def revoke_side_effect_approval(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        actor: str,
        reason: str,
    ) -> CoordinationResult:
        """Revoke a queued/pending task grant before worker execution begins."""
        task = self._require_task_for_update(task_id=task_id, tenant_id=tenant_id)
        if task.status not in {
            ExecutionTaskState.PENDING_REVIEW.value,
            ExecutionTaskState.QUEUED.value,
        }:
            raise ValueError(f"approval cannot be revoked from task status '{task.status}'")
        metadata = dict(task.metadata_json or {})
        constraints = dict(metadata.get("execution_constraints") or {})
        raw_grant = constraints.get("side_effect_authorization")
        if not isinstance(raw_grant, dict) or raw_grant.get("schema_version") != 2:
            raise ValueError("task has no revocable side-effect approval")
        if raw_grant.get("revoked_at") is not None:
            raise ValueError("side-effect approval is already revoked")
        revoked_at = datetime.now(UTC).isoformat()
        grant = dict(raw_grant)
        grant["revoked_at"] = revoked_at
        grant["revoked_by"] = actor
        grant["revocation_reason"] = reason
        constraints["side_effect_authorization"] = grant
        metadata["execution_constraints"] = constraints
        task.metadata_json = metadata
        self._governance.append(
            GovernanceEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                event_type="human_review_revoked",
                actor=actor,
                decision="revoked",
                payload_json={
                    "task_id": str(task.id),
                    "grant_id": grant.get("grant_id"),
                    "reason": reason,
                    "revoked_at": revoked_at,
                },
            )
        )
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="compliance",
                action="task_review_revoked",
                actor=actor,
                details=f"Side-effect approval for task {task.id} was revoked before execution.",
                payload_json={
                    "task_id": str(task.id),
                    "grant_id": grant.get("grant_id"),
                    "reason": reason,
                    "revoked_at": revoked_at,
                },
            )
        )
        self._session.flush()
        return CoordinationResult(ok=True, task_id=task.id, state=task.status, reason="approval_revoked")

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
