from __future__ import annotations

import uuid as _uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_platform_permission, require_route_permission
from backend.app.dependencies.db import get_db_session, get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.permissions import Permission
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
    require_route_permission(request=request, db=db, permission=Permission.RUNTIME_VIEW, tenant_id=tenant_id)
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
    require_route_permission(request=request, db=db, permission=Permission.RUNTIME_OPERATE, tenant_id=tenant_id)
    try:
        return OperationsService(db, queue).retry_dead_letter(tenant_id=str(tenant_id), task_id=task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/recovery")
def trigger_recovery(
    request: Request,
    db: Session = Depends(get_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, int]:
    """Trigger global lease recovery under explicit platform authority.

    This operation scans expired leases across all tenants. It is deliberately
    tenant-header-exempt but authentication-required and cannot be authorized by
    tenant ``runtime:operate`` permission. Only the platform control-plane
    permission may invoke it.
    """
    require_platform_permission(request=request, db=db, permission=Permission.PLATFORM_OPERATE)
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    actor = str(getattr(principal, "subject_id", "") or "").strip()
    actor_tenant_id = str(getattr(principal, "tenant_id", "") or "").strip()
    if not actor or not actor_tenant_id:
        raise HTTPException(status_code=403, detail="platform operator identity required")

    summary = OperationsService(db, queue).trigger_recovery(
        actor=actor,
        actor_tenant_id=actor_tenant_id,
    )
    return {
        "expired_lease_count": summary.expired_lease_count,
        "requeued_task_count": summary.requeued_task_count,
        "dead_lettered_count": summary.dead_lettered_count,
    }
