from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.domain.enums import ExecutionTaskState
from backend.queue.base import QueueAdapter
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.mission_executor import MissionExecutor
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError

router = APIRouter(prefix="/missions", tags=["missions"])

_REQUEST_TENANT_ID = Depends(get_request_tenant_id)
_TENANT_DB_SESSION = Depends(get_tenant_db_session)
_QUEUE_ADAPTER = Depends(get_queue_adapter)


def _tenant_uuid_or_400(tenant_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-Id must be a UUID") from exc


def _quota_detail(exc: QuotaExceededError) -> dict[str, Any]:
    return {
        "code": "QUOTA_EXCEEDED",
        "field": exc.field,
        "limit": exc.limit,
        "current": exc.current,
        "plan": exc.plan,
    }


@router.post("/{mission_id}/queue")
def queue_mission(
    mission_id: UUID,
    tenant_id: str = _REQUEST_TENANT_ID,
    db: Session = _TENANT_DB_SESSION,
    queue: QueueAdapter = _QUEUE_ADAPTER,
) -> dict[str, list[str]]:
    planned_tasks = [
        task
        for task in ExecutionTaskRepository(db).list_for_mission(mission_id)
        if str(task.tenant_id) == tenant_id and task.status == ExecutionTaskState.PLANNED.value
    ]

    if not planned_tasks:
        return {"queued_task_ids": []}

    try:
        QuotaEnforcementService(db).check_and_record_task_creation(
            _tenant_uuid_or_400(tenant_id),
            count=len(planned_tasks),
        )
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=_quota_detail(exc)) from exc

    executor = MissionExecutor(db, ExecutionCoordinator(db, queue))
    try:
        queued = executor.queue_all_planned_tasks(tenant_id=tenant_id, mission_id=mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"queued_task_ids": [str(task_id) for task_id in queued]}
