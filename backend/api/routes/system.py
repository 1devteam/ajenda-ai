from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.services.system_status_service import SystemStatusService

router = APIRouter(tags=["system"])


@router.get("/system/health")
def system_health() -> dict[str, str]:
    """Infrastructure liveness check.

    Public route that only proves the API process is serving requests.
    No database or queue dependency probes are performed here.
    """
    return SystemStatusService(session=None).health()


@router.get("/system/readiness")
def system_readiness(request: Request, response: Response) -> dict[str, object]:
    """Infrastructure dependency readiness check.

    Public route that evaluates app-level runtime dependencies
    (database runtime and configured queue adapter).
    """
    payload = SystemStatusService(session=None).readiness(
        database_runtime=getattr(request.app.state, "database_runtime", None),
        queue_adapter=getattr(request.app.state, "queue_adapter", None),
    )
    if payload["status"] != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload


@router.get("/system/status")
def system_status(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, dict[str, int]]:
    """Return operational status for the authenticated tenant.

    Tenant-facing route that remains separate from public liveness/readiness.
    Uses get_tenant_db_session to activate tenant RLS context.
    """
    return SystemStatusService(db).status(tenant_id=str(tenant_id))
