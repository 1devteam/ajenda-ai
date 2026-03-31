from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.queue.base import QueueAdapter
from backend.services.operations_service import OperationsService

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/dead-letter")
def dead_letter_inspection(
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> list[dict[str, str]]:
    return OperationsService(db, queue).inspect_dead_letter(tenant_id=tenant_id)


@router.post("/dead-letter/{task_id}/retry")
def retry_dead_letter(
    task_id: UUID,
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, str]:
    try:
        return OperationsService(db, queue).retry_dead_letter(tenant_id=tenant_id, task_id=task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/recovery")
def trigger_recovery(
    db: Session = Depends(get_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, int]:
    summary = OperationsService(db, queue).trigger_recovery()
    return {
        "expired_lease_count": summary.expired_lease_count,
        "requeued_task_count": summary.requeued_task_count,
    }
