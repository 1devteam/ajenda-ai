from __future__ import annotations

import uuid as _uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session, get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.queue.base import QueueAdapter
from backend.services.operations_service import OperationsService

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/dead-letter")
def dead_letter_inspection(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> list[dict[str, str]]:
    """List dead-lettered tasks for the authenticated tenant."""
    return OperationsService(db, queue).inspect_dead_letter(tenant_id=str(tenant_id))


@router.post("/dead-letter/{task_id}/retry")
def retry_dead_letter(
    task_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, str]:
    """Retry a dead-lettered task for the authenticated tenant."""
    try:
        return OperationsService(db, queue).retry_dead_letter(tenant_id=str(tenant_id), task_id=task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/recovery")
def trigger_recovery(
    db: Session = Depends(get_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, int]:
    """Trigger global lease recovery.

    Cross-tenant control-plane operation. Uses get_db_session intentionally —
    recovery scans all tenants' expired leases and is not tenant-scoped.
    See: docs/policies/TENANT_ISOLATION_AND_TENANT_DB_SESSION_POLICY.md §4.2
    """
    summary = OperationsService(db, queue).trigger_recovery()
    return {
        "expired_lease_count": summary.expired_lease_count,
        "requeued_task_count": summary.requeued_task_count,
    }
