from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState, MissionState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.outcome_review import OutcomeReview
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueAdapter
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.lineage_record_repository import LineageRecordRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.outcome_review_repository import OutcomeReviewRepository
from backend.repositories.worker_lease_repository import WorkerLeaseRepository
from backend.runtime.state_machine import InvalidTransitionError
from backend.runtime.transitions import transition_lease, transition_mission, transition_task
from backend.services.tools.evidence_bridge import build_tool_action_evidence_records
from backend.services.tools.mission_input_binding import handler_output_for_task, pending_dependency_keys

logger = logging.getLogger("ajenda.worker_runtime_service")


def _mirror_task_output_to_metadata(task_output: dict[str, Any]) -> dict[str, Any]:
    """Project handler output onto task metadata for API/poll consumers."""

    nested_output = task_output.get("output")
    return {
        "handler_result": task_output,
        "output": nested_output if nested_output is not None else task_output,
    }


def _task_action_name(task: ExecutionTask) -> str | None:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    invocation = metadata.get("tool_invocation")
    if isinstance(invocation, dict):
        action = invocation.get("action")
        if isinstance(action, str) and action.strip():
            return action.strip()
    return None


def _observe_accept_unmet(siblings: list[ExecutionTask]) -> bool:
    """True when an observe-contacts task finished without meeting the requested count."""

    for item in siblings:
        if _task_action_name(item) != "research.observe_contacts":
            continue
        if item.status != ExecutionTaskState.COMPLETED.value:
            continue
        output = handler_output_for_task(item)
        if output.get("accept_met") is True:
            return False
        return True
    return False


_TERMINAL_TASK_STATES: frozenset[str] = frozenset(
    {
        ExecutionTaskState.COMPLETED.value,
        ExecutionTaskState.FAILED.value,
        ExecutionTaskState.CANCELLED.value,
        ExecutionTaskState.DEAD_LETTERED.value,
        ExecutionTaskState.BLOCKED.value,
    }
)


class WorkerRuntimeService:
    def __init__(self, session: Session, queue: QueueAdapter) -> None:
        self._session = session
        self._queue = queue
        self._tasks = ExecutionTaskRepository(session)
        self._leases = WorkerLeaseRepository(session)
        self._audit = AuditEventRepository(session)

    def claim_next_task(self, *, tenant_id: str, worker_id: str) -> ExecutionTask | None:
        message = self._queue.claim_task(tenant_id=tenant_id, worker_id=worker_id)
        if message is None:
            return None

        task = self._tasks.get(message.task_id)
        if task is None or task.tenant_id != tenant_id:
            logger.error(
                "claim_task_not_in_db",
                extra={"task_id": str(message.task_id), "worker_id": worker_id},
            )
            self._queue.release_lease(
                tenant_id=tenant_id,
                task_id=message.task_id,
                worker_id=worker_id,
            )
            return None

        if task.status in _TERMINAL_TASK_STATES:
            self._reconcile_claimed_terminal_queue_artifact(
                tenant_id=tenant_id,
                task=task,
                worker_id=worker_id,
            )
            return None

        savepoint = self._session.begin_nested()
        try:
            self._assert_no_active_lease(tenant_id=tenant_id, task_id=task.id)
            transition_task(task, ExecutionTaskState.CLAIMED)
            lease = self._leases.add(
                WorkerLease(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    status=WorkerLeaseState.CLAIMED.value,
                    holder_identity=worker_id,
                    heartbeat_at=datetime.now(UTC),
                )
            )
            task.metadata_json = {**task.metadata_json, "worker_lease_id": str(lease.id)}
            self._session.flush()

            # Ability graph: do not start work until dependency_keys are completed.
            if task.mission_id is not None:
                mission_tasks = self._tasks.list_for_mission(mission_id=task.mission_id)
                pending = pending_dependency_keys(task=task, mission_tasks=mission_tasks)
                if pending:
                    logger.info(
                        "claim_deferred_dependencies",
                        extra={
                            "task_id": str(task.id),
                            "pending_keys": pending,
                            "worker_id": worker_id,
                        },
                    )
                    self._transition_lease_to_released(lease)
                    transition_task(task, ExecutionTaskState.QUEUED)
                    task.metadata_json = {
                        **(task.metadata_json if isinstance(task.metadata_json, dict) else {}),
                        "dependency_deferral": {
                            "pending_keys": pending,
                            "deferred_at": datetime.now(UTC).isoformat(),
                        },
                    }
                    # Drop worker_lease_id so a later claim creates a fresh lease.
                    meta = dict(task.metadata_json)
                    meta.pop("worker_lease_id", None)
                    task.metadata_json = meta
                    self._session.flush()
                    savepoint.commit()
                    self._session.commit()
                    self._queue.release_lease(
                        tenant_id=tenant_id,
                        task_id=task.id,
                        worker_id=worker_id,
                    )
                    return None

            savepoint.commit()
            self._session.commit()
        except Exception as exc:
            logger.error(
                "claim_db_failed_releasing_queue_claim",
                extra={"task_id": str(task.id), "worker_id": worker_id, "error": str(exc)},
            )
            if savepoint.is_active:
                savepoint.rollback()
            else:
                self._session.rollback()
            try:
                self._queue.release_lease(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    worker_id=worker_id,
                )
            except Exception as release_exc:
                logger.critical(
                    "claim_compensation_failed",
                    extra={
                        "task_id": str(task.id),
                        "worker_id": worker_id,
                        "release_error": str(release_exc),
                    },
                )
            raise

        return task

    def heartbeat(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> WorkerLease:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        if lease.status not in {WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value}:
            raise ValueError("lease is not heartbeat-eligible")

        result = self._queue.heartbeat(tenant_id=tenant_id, task_id=lease.task_id, worker_id=worker_id)
        if not result.ok:
            raise ValueError(result.reason or "heartbeat rejected")

        if lease.status == WorkerLeaseState.CLAIMED.value:
            transition_lease(lease, WorkerLeaseState.ACTIVE)
        lease.heartbeat_at = datetime.now(UTC)
        self._session.flush()
        self._session.commit()
        return lease

    def start_execution(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> ExecutionTask:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status == ExecutionTaskState.CLAIMED.value:
            if lease.status == WorkerLeaseState.CLAIMED.value:
                transition_lease(lease, WorkerLeaseState.ACTIVE)
            lease.heartbeat_at = datetime.now(UTC)
            transition_task(task, ExecutionTaskState.RUNNING)
            self._session.flush()
            self._session.commit()
        return task

    def complete(
        self,
        *,
        tenant_id: str,
        lease_id: uuid.UUID,
        worker_id: str,
        task_output: dict[str, Any] | None = None,
        output_reason: str | None = None,
    ) -> ExecutionTask:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status != ExecutionTaskState.RUNNING.value:
            raise ValueError("task is not running")

        transition_task(task, ExecutionTaskState.COMPLETED)
        self._transition_lease_to_released(lease)
        lease.heartbeat_at = datetime.now(UTC)
        evidence_ids_for_review: list[str] = []
        if task_output is not None:
            task.metadata_json = {**task.metadata_json, **_mirror_task_output_to_metadata(task_output)}
            lineage_record = LineageRecordRepository(self._session).append(
                LineageRecord(
                    tenant_id=task.tenant_id,
                    mission_id=task.mission_id,
                    fleet_id=task.fleet_id,
                    branch_id=task.branch_id,
                    task_id=task.id,
                    worker_lease_id=lease.id,
                    relationship_type="task_output",
                    relationship_reason=output_reason,
                    metadata_json=task_output,
                )
            )
            evidence_repo = EvidenceRepository(self._session)
            for evidence_record in build_tool_action_evidence_records(
                task=task,
                lease=lease,
                task_output=task_output,
                lineage_record=lineage_record,
            ):
                added = evidence_repo.add(evidence_record)
                evidence_ids_for_review.append(str(added.id))

            # Outcome review bridge for high-risk GTM side-effecting actions (PR pilot coherence)
            # Auto-creates a draft review post-completion for missions launched with high-risk GTM
            # via ability-runtime (where requires_human_review and side_effect_authorization are set).
            # This fulfills the "completion + evidence + outcome review" stage and removes
            # "create_outcome_review" from mission lifecycle missing steps.
            # Creation is internal (no permission gate) and respects OutcomeReview contract
            # (no runtime mutation).
            if self._is_high_risk_gtm_side_effect(task, task_output):
                self._create_draft_outcome_review(
                    task=task,
                    task_output=task_output,
                    evidence_ids=evidence_ids_for_review,
                )

        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="worker",
                action="task_completed",
                actor=worker_id,
                details=f"Completed task {task.id}",
                payload_json={"task_id": str(task.id), "lease_id": str(lease.id)},
            )
        )
        self._maybe_rollup_mission_status(task=task, worker_id=worker_id)
        self._session.flush()
        self._session.commit()

        result = self._queue.complete_task(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
        if not result.ok:
            self._record_terminal_queue_cleanup_failure(
                tenant_id=tenant_id,
                task=task,
                lease=lease,
                worker_id=worker_id,
                queue_operation="complete_task",
                audit_action="terminal_queue_complete_cleanup_failed",
                reason=result.reason or "complete rejected",
            )
        return task

    def _maybe_rollup_mission_status(self, *, task: ExecutionTask, worker_id: str) -> None:
        """Advance mission status when graph tasks finish (composition path stays planned today)."""

        if task.mission_id is None:
            return
        mission = MissionRepository(self._session).get_for_tenant(
            mission_id=task.mission_id,
            tenant_id=task.tenant_id,
        )
        if mission is None:
            return
        # Do not reopen terminal missions.
        if mission.status in {
            MissionState.COMPLETED.value,
            MissionState.FAILED.value,
            MissionState.CANCELLED.value,
            MissionState.ARCHIVED.value,
        }:
            return

        siblings = self._tasks.list_for_mission(task.mission_id)
        if not siblings:
            return
        open_tasks = [item for item in siblings if item.status not in _TERMINAL_TASK_STATES]
        failedish = {
            ExecutionTaskState.FAILED.value,
            ExecutionTaskState.DEAD_LETTERED.value,
            ExecutionTaskState.BLOCKED.value,
        }
        try:
            if open_tasks:
                # First successful completion while others remain → running.
                if mission.status in {
                    MissionState.PLANNED.value,
                    MissionState.APPROVED.value,
                    MissionState.QUEUED.value,
                }:
                    transition_mission(mission, MissionState.RUNNING)
                    self._session.add(mission)
                    self._audit.append(
                        AuditEvent(
                            tenant_id=task.tenant_id,
                            mission_id=task.mission_id,
                            category="mission",
                            action="mission_running",
                            actor=worker_id,
                            details=f"Mission {task.mission_id} marked running after task {task.id}",
                            payload_json={"task_id": str(task.id), "open_tasks": len(open_tasks)},
                        )
                    )
                return

            # All graph tasks terminal.
            any_failed = any(item.status in failedish for item in siblings)
            accept_unmet = _observe_accept_unmet(siblings)
            target = MissionState.FAILED if any_failed or accept_unmet else MissionState.COMPLETED
            if mission.status != MissionState.RUNNING.value:
                # Hop through running when coming from planned/queued so state machine stays honest.
                if mission.status in {
                    MissionState.PLANNED.value,
                    MissionState.APPROVED.value,
                    MissionState.QUEUED.value,
                }:
                    transition_mission(mission, MissionState.RUNNING)
            transition_mission(mission, target)
            self._session.add(mission)
            self._audit.append(
                AuditEvent(
                    tenant_id=task.tenant_id,
                    mission_id=task.mission_id,
                    category="mission",
                    action="mission_completed" if target == MissionState.COMPLETED else "mission_failed",
                    actor=worker_id,
                    details=f"Mission {task.mission_id} rolled up to {target.value} after graph terminalization",
                    payload_json={
                        "task_id": str(task.id),
                        "task_count": len(siblings),
                        "mission_status": target.value,
                    },
                )
            )
        except InvalidTransitionError as exc:
            logger.warning(
                "mission_status_rollup_skipped",
                extra={
                    "mission_id": str(task.mission_id),
                    "mission_status": mission.status,
                    "reason": str(exc),
                },
            )

    def block_completion_failure(
        self,
        *,
        tenant_id: str,
        lease_id: uuid.UUID,
        worker_id: str,
        task_type: str,
        side_effect_class: str,
        reason: str,
    ) -> ExecutionTask:
        """Block a task after a side-effecting handler completed but completion persistence failed."""

        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status != ExecutionTaskState.RUNNING.value:
            raise ValueError("task is not running")

        transition_task(task, ExecutionTaskState.BLOCKED)
        self._transition_lease_to_released(lease)
        lease.heartbeat_at = datetime.now(UTC)
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="worker",
                action="task_completion_failed_after_side_effect",
                actor=worker_id,
                details=(f"Blocked task {task.id} after completed {task_type} side effect failed completion: {reason}"),
                payload_json={
                    "task_id": str(task.id),
                    "lease_id": str(lease.id),
                    "task_type": task_type,
                    "side_effect_class": side_effect_class,
                    "reason": reason,
                    "handler_completed": True,
                    "requeue_allowed": False,
                },
            )
        )
        self._session.flush()
        self._session.commit()

        result = self._queue.complete_task(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
        if not result.ok:
            self._record_terminal_queue_cleanup_failure(
                tenant_id=tenant_id,
                task=task,
                lease=lease,
                worker_id=worker_id,
                queue_operation="complete_task",
                audit_action="completion_failure_queue_complete_cleanup_failed",
                reason=result.reason or "complete rejected",
            )
        return task

    def fail(
        self,
        *,
        tenant_id: str,
        lease_id: uuid.UUID,
        worker_id: str,
        reason: str,
    ) -> ExecutionTask:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status not in {
            ExecutionTaskState.CLAIMED.value,
            ExecutionTaskState.RUNNING.value,
            ExecutionTaskState.BLOCKED.value,
        }:
            raise ValueError("task is not fail-eligible")

        transition_task(task, ExecutionTaskState.FAILED)
        self._transition_lease_to_released(lease)
        lease.heartbeat_at = datetime.now(UTC)
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="worker",
                action="task_failed",
                actor=worker_id,
                details=reason,
                payload_json={"task_id": str(task.id), "lease_id": str(lease.id)},
            )
        )
        self._session.flush()
        self._session.commit()

        result = self._queue.fail_task(
            tenant_id=tenant_id,
            task_id=task.id,
            worker_id=worker_id,
            reason=reason,
        )
        if not result.ok:
            self._record_terminal_queue_cleanup_failure(
                tenant_id=tenant_id,
                task=task,
                lease=lease,
                worker_id=worker_id,
                queue_operation="fail_task",
                audit_action="terminal_queue_fail_cleanup_failed",
                reason=result.reason or "fail rejected",
            )
        return task

    def release(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> WorkerLease:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        self._assert_current_releasable_claim(tenant_id=tenant_id, lease=lease, task=task)

        self._transition_lease_to_released(lease)
        transition_task(task, ExecutionTaskState.QUEUED)
        result = self._queue.release_lease(
            tenant_id=tenant_id,
            task_id=lease.task_id,
            worker_id=worker_id,
        )
        if not result.ok:
            self._session.rollback()
            raise ValueError(result.reason or "release rejected")
        lease.heartbeat_at = datetime.now(UTC)
        self._session.flush()
        self._session.commit()
        return lease

    def _reconcile_claimed_terminal_queue_artifact(
        self,
        *,
        tenant_id: str,
        task: ExecutionTask,
        worker_id: str,
    ) -> None:
        try:
            result = self._queue.complete_task(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
            cleanup_ok = result.ok
            reason = result.reason or "complete rejected"
        except Exception as exc:
            cleanup_ok = False
            reason = f"complete_task raised: {exc}"

        action = "terminal_task_queue_claim_reconciled" if cleanup_ok else "terminal_task_queue_claim_cleanup_failed"
        if cleanup_ok:
            details = f"Removed stale queue claim for terminal task {task.id}."
            logger.info(
                "terminal_task_queue_claim_reconciled",
                extra={
                    "tenant_id": tenant_id,
                    "task_id": str(task.id),
                    "task_status": task.status,
                    "worker_id": worker_id,
                },
            )
        else:
            details = f"Queue cleanup failed for terminal task {task.id}: {reason}"
            logger.critical(
                "terminal_task_queue_claim_cleanup_failed",
                extra={
                    "tenant_id": tenant_id,
                    "task_id": str(task.id),
                    "task_status": task.status,
                    "worker_id": worker_id,
                    "reason": reason,
                },
            )

        try:
            self._audit.append(
                AuditEvent(
                    tenant_id=tenant_id,
                    mission_id=task.mission_id,
                    category="worker_queue_cleanup",
                    action=action,
                    actor=worker_id,
                    details=details,
                    payload_json={
                        "task_id": str(task.id),
                        "task_status": task.status,
                        "queue_operation": "complete_task",
                        "cleanup_succeeded": cleanup_ok,
                        "reason": None if cleanup_ok else reason,
                        "requeue_allowed": False,
                    },
                )
            )
            self._session.flush()
            self._session.commit()
        except Exception as exc:
            self._session.rollback()
            logger.critical(
                "terminal_task_queue_claim_reconciliation_audit_failed",
                extra={
                    "tenant_id": tenant_id,
                    "task_id": str(task.id),
                    "task_status": task.status,
                    "worker_id": worker_id,
                    "cleanup_succeeded": cleanup_ok,
                    "cleanup_reason": reason,
                    "audit_error": str(exc),
                },
            )

    def _record_terminal_queue_cleanup_failure(
        self,
        *,
        tenant_id: str,
        task: ExecutionTask,
        lease: WorkerLease,
        worker_id: str,
        queue_operation: str,
        audit_action: str,
        reason: str,
    ) -> None:
        logger.critical(
            f"queue_{queue_operation}_after_db_commit_failed",
            extra={
                "tenant_id": tenant_id,
                "task_id": str(task.id),
                "task_status": task.status,
                "lease_id": str(lease.id),
                "lease_status": lease.status,
                "worker_id": worker_id,
                "reason": reason,
            },
        )
        try:
            self._audit.append(
                AuditEvent(
                    tenant_id=tenant_id,
                    mission_id=task.mission_id,
                    category="worker_queue_cleanup",
                    action=audit_action,
                    actor=worker_id,
                    details=(
                        f"Queue {queue_operation} cleanup failed after DB terminal commit for task {task.id}: {reason}"
                    ),
                    payload_json={
                        "task_id": str(task.id),
                        "task_status": task.status,
                        "lease_id": str(lease.id),
                        "lease_status": lease.status,
                        "queue_operation": queue_operation,
                        "reason": reason,
                        "requeue_allowed": False,
                    },
                )
            )
            self._session.flush()
            self._session.commit()
        except Exception as exc:
            self._session.rollback()
            logger.critical(
                "terminal_queue_cleanup_failure_audit_persist_failed",
                extra={
                    "tenant_id": tenant_id,
                    "task_id": str(task.id),
                    "lease_id": str(lease.id),
                    "queue_operation": queue_operation,
                    "queue_reason": reason,
                    "audit_error": str(exc),
                },
            )

    def _assert_current_releasable_claim(
        self,
        *,
        tenant_id: str,
        lease: WorkerLease,
        task: ExecutionTask,
    ) -> None:
        if lease.status not in {WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value}:
            raise ValueError("lease is not release-eligible")
        if task.tenant_id != tenant_id or lease.tenant_id != tenant_id:
            raise ValueError("task not found for tenant lease")
        if task.status != ExecutionTaskState.CLAIMED.value:
            raise ValueError("task is not claimed")
        if not isinstance(task.metadata_json, dict) or task.metadata_json.get("worker_lease_id") != str(lease.id):
            raise ValueError("lease is not current task claim")

    def _get_owned_lease(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> WorkerLease:
        lease = self._leases.get(lease_id)
        if lease is None or lease.tenant_id != tenant_id or lease.holder_identity != worker_id:
            raise ValueError("lease not found for tenant worker")
        return lease

    def _get_task_for_lease(self, lease: WorkerLease) -> ExecutionTask:
        task = self._tasks.get(lease.task_id)
        if task is None:
            raise ValueError("task not found")
        return task

    def _assert_no_active_lease(self, *, tenant_id: str, task_id: uuid.UUID) -> None:
        stmt = select(WorkerLease).where(
            WorkerLease.tenant_id == tenant_id,
            WorkerLease.task_id == task_id,
            WorkerLease.status.in_([WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value]),
        )
        existing = self._session.scalars(stmt).first()
        if existing is not None:
            raise ValueError("task already has an active lease")

    def _transition_lease_to_released(self, lease: WorkerLease) -> None:
        if lease.status == WorkerLeaseState.RELEASED.value:
            return
        if lease.status == WorkerLeaseState.CLAIMED.value:
            transition_lease(lease, WorkerLeaseState.ACTIVE)
        transition_lease(lease, WorkerLeaseState.RELEASED)

    # --- Outcome Review Bridge helpers (for high-risk GTM pilot coherence) ---

    def _gtm_side_effect_was_real(self, task_output: dict[str, Any]) -> bool:
        nested = task_output.get("output")
        if isinstance(nested, dict) and "real" in nested:
            return bool(nested.get("real"))
        return bool(task_output.get("real"))

    def _is_high_risk_gtm_side_effect(self, task: ExecutionTask, task_output: dict[str, Any] | None) -> bool:
        if not task_output or not isinstance(task_output, dict):
            return False
        action = str(task_output.get("action", "") or "")
        side_effect_class = str(task_output.get("side_effect_class", "") or "")
        if not action.startswith("gtm."):
            return False
        if side_effect_class not in {"external_send", "external_write", "external_publish"}:
            return False
        return self._gtm_side_effect_was_real(task_output)

    def _create_draft_outcome_review(
        self,
        *,
        task: ExecutionTask,
        task_output: dict[str, Any],
        evidence_ids: list[str],
    ) -> None:
        """Create a draft OutcomeReview for high-risk GTM side-effect completion.

        Populates from task metadata (side_effect_authorization from PR9 launch) and
        the just-collected evidence. Idempotent-ish: skips if recent draft exists for mission.
        """
        try:
            repo = OutcomeReviewRepository(self._session)
            existing = repo.list_for_mission(mission_id=task.mission_id, tenant_id=task.tenant_id)
            for r in existing:
                if r.review_status in ("draft", "in_review"):
                    return  # already has active review

            metadata = task.metadata_json or {}
            tool_inv = metadata.get("tool_invocation", {}) or {}
            auth = (metadata.get("execution_constraints") or {}).get("side_effect_authorization", {}) or {}
            approved_by = auth.get("approved_by") or "system"
            reason = auth.get("reason") or "High-risk GTM side effect completed"

            action_name = tool_inv.get("action") or task_output.get("action", "gtm.unknown")

            review = OutcomeReview(
                tenant_id=task.tenant_id,
                mission_id=task.mission_id,
                task_graph_reference={"execution_task_id": str(task.id), "action": action_name},
                reviewed_success_criteria=[
                    {
                        "criteria": "high-risk GTM action completed with evidence and guardian approval",
                        "action": action_name,
                    }
                ],
                evidence_references=[{"evidence_id": eid} for eid in evidence_ids],
                review_status="draft",
                review_decision="inconclusive",
                reviewer_type="system",
                reviewer_source=approved_by,
                review_summary=f"Auto-generated draft from completion of high-risk GTM action {action_name}. Reason: {reason}",
                structured_findings=[],
                confidence=None,
                trust_signal={
                    "source": "worker_runtime_completion_bridge",
                    "side_effect_authorization": auth,
                },
                unresolved_gaps=[],
                recommended_next_actions=[{"action": "human_review", "reason": "high-risk external side effect"}],
                human_approval_required=True,
                human_approval_status="pending",
            )
            repo.add(review)
        except Exception:
            # Best effort bridge; do not fail completion. Logged via audit elsewhere if needed.
            pass
