from __future__ import annotations

import uuid as _uuid
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.domain.enums import ExecutionTaskState
from backend.queue.base import QueueAdapter
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.mission_executor import MissionExecutor
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError

router = APIRouter(prefix="/missions", tags=["missions"])


@router.post("/{mission_id}/queue")
def queue_mission(
    mission_id: UUID,
    request: Request,
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, list[str]]:
    """Queue all planned tasks for a mission.

    Enforces task creation quota before queuing. The quota check uses the
    actual number of planned tasks that will be enqueued — not a flat 1 —
    so that tenants cannot bypass max_tasks_per_month by batching large
    missions into a single call.

    Returns HTTP 429 with structured body if the tenant has reached their
    plan limit.
    """
    tenant_uuid = _uuid.UUID(tenant_id)

    # --- Count planned tasks that will actually be enqueued ---
    task_repo = ExecutionTaskRepository(db)
    all_tasks = task_repo.list_for_mission(mission_id=mission_id)
    planned_tasks = [t for t in all_tasks if t.status == ExecutionTaskState.PLANNED.value]
    planned_count = len(planned_tasks)

    # --- Early return: no planned tasks, nothing to do ---
    if planned_count == 0:
        return {"queued_task_ids": []}

    # --- Quota check: consume N quota units for N tasks being queued ---
    try:
        QuotaEnforcementService(db).check_and_record_task_creation(tenant_uuid, count=planned_count)
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "QUOTA_EXCEEDED",
                "field": exc.field,
                "limit": exc.limit,
                "current": exc.current,
                "plan": exc.plan,
                "message": (
                    f"You have reached the {exc.field} limit ({exc.limit}) "
                    f"for the {exc.plan!r} plan. Upgrade to continue."
                ),
            },
        ) from exc

    executor = MissionExecutor(db, ExecutionCoordinator(db, queue))
    try:
        queued = executor.queue_all_planned_tasks(tenant_id=tenant_id, mission_id=mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"queued_task_ids": [str(task_id) for task_id in queued]}
