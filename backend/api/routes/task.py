from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.queue.base import QueueAdapter
from backend.services.execution_coordinator import ExecutionCoordinator

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/{task_id}/queue")
def queue_task(
    task_id: UUID,
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, str]:
    try:
        result = ExecutionCoordinator(db, queue).queue_task(tenant_id=tenant_id, task_id=task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result.ok:
        raise HTTPException(status_code=400, detail=result.reason or "task queue rejected")

    return {"task_id": str(result.task_id), "state": result.state}
