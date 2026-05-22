from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.services.system_status_service import SystemStatusService

router = APIRouter(tags=["system"])


@router.get("/system/health")
def system_health() -> dict[str, str]:
    """Infrastructure health check. Public — no tenant/auth and no runtime dependency checks."""
    return SystemStatusService().health()


@router.get("/system/readiness")
def system_readiness(request: Request, response: Response) -> dict[str, object]:
    """Infrastructure readiness check. Public; checks DB runtime and queue adapter dependency truth."""
    status_code, payload = SystemStatusService().readiness(
        database_runtime=getattr(request.app.state, "database_runtime", None),
        queue_adapter=getattr(request.app.state, "queue_adapter", None),
    )
    response.status_code = status_code
    return payload


@router.get("/system/status")
def system_status(
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, dict[str, int]]:
    """Return operational status for the authenticated tenant.

    Tenant-facing — uses get_tenant_db_session to activate RLS. See:
    docs/policies/TENANT_ISOLATION_AND_TENANT_DB_SESSION_POLICY.md §4.1
    """
    return SystemStatusService(db).status(tenant_id=str(tenant_id))
