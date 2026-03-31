from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.services.system_status_service import SystemStatusService

router = APIRouter(tags=["system"])


@router.get("/system/health")
def system_health(db: Session = Depends(get_db_session)) -> dict[str, str]:
    return SystemStatusService(db).health()


@router.get("/system/readiness")
def system_readiness(db: Session = Depends(get_db_session)) -> dict[str, str]:
    return SystemStatusService(db).readiness()


@router.get("/system/status")
def system_status(
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
) -> dict[str, dict[str, int]]:
    return SystemStatusService(db).status(tenant_id=tenant_id)
