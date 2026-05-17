from __future__ import annotations

import uuid as _uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_database_runtime, get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.db.session import DatabaseRuntime
from backend.queue.base import QueueAdapter
from backend.services.system_status_service import SystemStatusService

router = APIRouter(tags=["system"])


@router.get("/system/health")
def system_health() -> dict[str, str]:
    """Infrastructure health check. Public — no tenant context required.

    This is a lightweight process/system surface and intentionally does not
    perform database or queue dependency checks.
    """
    return SystemStatusService(session=None).health()


@router.get("/system/readiness")
def system_readiness(
    database_runtime: DatabaseRuntime = Depends(get_database_runtime),
    queue_adapter: QueueAdapter = Depends(get_queue_adapter),
) -> Any:
    """Infrastructure readiness check. Public — no tenant context required.

    Uses DatabaseRuntime.ping intentionally so dependency readiness checks do
    not participate in request transaction teardown.
    """
    readiness_status = SystemStatusService(
        database_runtime=database_runtime,
        queue_adapter=queue_adapter,
    ).readiness()
    if readiness_status["dependencies"] != "ready":
        return JSONResponse(status_code=503, content=readiness_status)
    return readiness_status


@router.get("/system/status")
def system_status(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, dict[str, int]]:
    """Return operational status for the authenticated tenant.

    Tenant-facing — uses get_tenant_db_session to activate RLS. See:
    docs/policies/TENANT_ISOLATION_AND_TENANT_DB_SESSION_POLICY.md §4.1
    """
    return SystemStatusService(session=db).status(tenant_id=str(tenant_id))
