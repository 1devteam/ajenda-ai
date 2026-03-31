from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.queue.base import QueueAdapter
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.mission_executor import MissionExecutor

router = APIRouter(prefix="/missions", tags=["missions"])


@router.post("/{mission_id}/queue")
def queue_mission(
    mission_id: UUID,
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, list[str]]:
    executor = MissionExecutor(db, ExecutionCoordinator(db, queue))
    try:
        queued = executor.queue_all_planned_tasks(tenant_id=tenant_id, mission_id=mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"queued_task_ids": [str(task_id) for task_id in queued]}
