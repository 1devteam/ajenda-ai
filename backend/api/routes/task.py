from __future__ import annotations

import uuid as _uuid
from uuid import UUID

from backend.api.errors import quota_exceeded_http
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.permissions import Permission
from backend.queue.base import QueueAdapter
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError

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

    Verifies tenant ownership before consuming quota so missing or foreign tasks
    do not burn task-creation allowance. Returns HTTP 429 with a structured body
    if the tenant has reached their plan limit.
    """
    require_route_permission(request=request, db=db, permission=Permission.EXECUTION_QUEUE, tenant_id=tenant_id)
    tenant_id_str = str(tenant_id)

    # --- Preflight: task must exist for the authenticated tenant before quota ---
    task = ExecutionTaskRepository(db).get(task_id)
    if task is None or task.tenant_id != tenant_id_str:
        raise HTTPException(status_code=400, detail="task not found for tenant")

    # --- Quota check: task creation ---
    try:
        QuotaEnforcementService(db).check_and_record_task_creation(tenant_id)
    except QuotaExceededError as exc:
        raise quota_exceeded_http(exc) from exc

    try:
        result = ExecutionCoordinator(db, queue).queue_task(tenant_id=tenant_id_str, task_id=task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result.ok:
        raise HTTPException(status_code=400, detail=result.reason or "task queue rejected")

    return {"task_id": str(result.task_id), "state": result.state}
