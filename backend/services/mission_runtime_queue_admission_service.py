from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState
from backend.domain.mission import MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY
from backend.queue.base import QueueAdapter
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_repository import MissionRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError


class MissionRuntimeQueueAdmissionService:
    """Sole authority for materialized mission task queue admission.

    The service serializes admission on the tenant-owned mission, selects the
    current materialization, enforces quota once for newly eligible tasks,
    delegates queue transitions to ``ExecutionCoordinator``, persists the
    authoritative admission receipt, and returns the projection consumed by
    every mission-level API adapter.
    """

    def __init__(
        self,
        db: Session,
        queue: QueueAdapter,
        *,
        mission_repository_cls: Any = MissionRepository,
        execution_task_repository_cls: Any = ExecutionTaskRepository,
        quota_enforcement_service_cls: Any = QuotaEnforcementService,
        execution_coordinator_cls: Any = ExecutionCoordinator,
    ) -> None:
        self._db = db
        self._queue = queue
        self._mission_repository_cls = mission_repository_cls
        self._execution_task_repository_cls = execution_task_repository_cls
        self._quota_enforcement_service_cls = quota_enforcement_service_cls
        self._execution_coordinator_cls = execution_coordinator_cls

    def admit(self, *, mission_id: UUID, tenant_id: UUID) -> dict[str, object]:
        from backend.services.mission_bridge.queue_admission import (
            build_runtime_queue_admission_metadata,
            current_materialized_execution_task_ids,
            runtime_queue_admission_blocker,
            runtime_queue_admission_response,
        )
        from backend.services.mission_bridge.quota import quota_exceeded_response

        tenant_id_str = str(tenant_id)
        mission_repo = self._mission_repository_cls(self._db)
        mission = mission_repo.lock_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
        if mission is None:
            raise HTTPException(status_code=404, detail="mission not found for tenant")

        metadata = dict(mission.metadata_json or {})
        materialized_task_ids = current_materialized_execution_task_ids(metadata)
        task_repo = self._execution_task_repository_cls(self._db)
        tasks_by_id = {task.id: task for task in task_repo.list_for_mission(mission_id=mission_id)}

        tasks_to_queue: list[Any] = []
        already_queued_task_ids: list[str] = []
        blockers: list[dict[str, Any]] = []
        if not materialized_task_ids:
            blockers.append(
                runtime_queue_admission_blocker(
                    task_id=None,
                    code="no_current_materialized_tasks",
                    message="Mission has no current materialized execution tasks for queue admission.",
                )
            )
        for task_id in materialized_task_ids:
            task = tasks_by_id.get(task_id)
            if task is None:
                blockers.append(
                    runtime_queue_admission_blocker(
                        task_id=task_id,
                        code="materialized_task_missing",
                        message="Materialized execution task row was not found for this mission.",
                    )
                )
                continue
            if task.tenant_id != tenant_id_str or task.mission_id != mission_id:
                blockers.append(
                    runtime_queue_admission_blocker(
                        task_id=task_id,
                        code="materialized_task_scope_mismatch",
                        message="Materialized execution task is not owned by this tenant and mission.",
                        state=task.status,
                    )
                )
                continue
            if task.status == ExecutionTaskState.PLANNED.value:
                tasks_to_queue.append(task)
                continue
            if task.status == ExecutionTaskState.QUEUED.value:
                already_queued_task_ids.append(str(task.id))
                continue
            blockers.append(
                runtime_queue_admission_blocker(
                    task_id=task.id,
                    code="materialized_task_not_queueable",
                    message="Materialized execution task is not planned or already queued.",
                    state=task.status,
                )
            )

        if tasks_to_queue:
            try:
                self._quota_enforcement_service_cls(self._db).check_and_record_task_creation(
                    tenant_id, count=len(tasks_to_queue)
                )
            except QuotaExceededError as exc:
                raise quota_exceeded_response(exc) from exc

        coordinator = self._execution_coordinator_cls(self._db, self._queue)
        queued_task_ids: list[str] = []
        pending_review_task_ids: list[str] = []
        denied_tasks: list[dict[str, str | None]] = []
        for task in tasks_to_queue:
            try:
                result = coordinator.queue_task(tenant_id=tenant_id_str, task_id=task.id)
            except Exception as exc:
                blockers.append(
                    runtime_queue_admission_blocker(
                        task_id=task.id,
                        code="queue_task_failed",
                        message="Execution coordinator failed to queue the materialized task.",
                        state=task.status,
                        reason=str(exc),
                    )
                )
                continue
            if result.ok:
                queued_task_ids.append(str(task.id))
                continue
            if result.state == ExecutionTaskState.PENDING_REVIEW.value:
                pending_review_task_ids.append(str(task.id))
                blockers.append(
                    runtime_queue_admission_blocker(
                        task_id=task.id,
                        code="policy_review_required",
                        message="Execution coordinator routed the materialized task to policy review.",
                        state=result.state,
                        reason=result.reason,
                    )
                )
                continue
            denied_task = {"task_id": str(task.id), "state": result.state, "reason": result.reason}
            denied_tasks.append(denied_task)
            blockers.append(
                runtime_queue_admission_blocker(
                    task_id=task.id,
                    code="runtime_governor_denied",
                    message="Runtime governor denied queue admission for the materialized task.",
                    state=result.state,
                    reason=result.reason,
                )
            )

        queue_admission_metadata = build_runtime_queue_admission_metadata(
            mission_id=mission_id,
            tenant_id=tenant_id_str,
            materialized_task_ids=materialized_task_ids,
            planned_task_ids=[str(task.id) for task in tasks_to_queue],
            queued_task_ids=queued_task_ids,
            already_queued_task_ids=already_queued_task_ids,
            pending_review_task_ids=pending_review_task_ids,
            denied_tasks=denied_tasks,
            blockers=blockers,
            now=datetime.now(UTC).isoformat(),
        )
        metadata[MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY] = queue_admission_metadata
        mission_repo.update_metadata(mission=mission, metadata_json=metadata)
        return runtime_queue_admission_response(queue_admission_metadata)
