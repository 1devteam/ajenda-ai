from __future__ import annotations

import uuid as _uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.permissions import Permission
from backend.queue.base import QueueAdapter
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.services.execution_coordinator import ExecutionCoordinator

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/{task_id}/queue")
def queue_task(
    task_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, str]:
    """Queue a single task for execution.

    Verifies tenant ownership before queueing. Queueing an existing task does
    not consume the tasks_created quota counter; that counter is reserved for
    ExecutionTask row creation paths.
    """
    require_route_permission(request=request, db=db, permission=Permission.EXECUTION_QUEUE, tenant_id=tenant_id)
    tenant_id_str = str(tenant_id)

    # --- Preflight: task must exist for the authenticated tenant before quota ---
    task = ExecutionTaskRepository(db).get(task_id)
    if task is None or task.tenant_id != tenant_id_str:
        raise HTTPException(status_code=400, detail="task not found for tenant")

    try:
        result = ExecutionCoordinator(db, queue).queue_task(tenant_id=tenant_id_str, task_id=task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result.ok:
        raise HTTPException(status_code=400, detail=result.reason or "task queue rejected")

    return {"task_id": str(result.task_id), "state": result.state}
