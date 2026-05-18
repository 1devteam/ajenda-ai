from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.queue.base import QueueAdapter
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError

router = APIRouter(prefix="/tasks", tags=["tasks"])

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


@router.post("/{task_id}/queue")
def queue_task(
    task_id: UUID,
    tenant_id: str = _REQUEST_TENANT_ID,
    db: Session = _TENANT_DB_SESSION,
    queue: QueueAdapter = _QUEUE_ADAPTER,
) -> dict[str, str]:
    try:
        QuotaEnforcementService(db).check_and_record_task_creation(_tenant_uuid_or_400(tenant_id))
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=_quota_detail(exc)) from exc

    try:
        result = ExecutionCoordinator(db, queue).queue_task(tenant_id=tenant_id, task_id=task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result.ok:
        raise HTTPException(status_code=400, detail=result.reason or "task queue rejected")

    return {"task_id": str(result.task_id), "state": result.state}
