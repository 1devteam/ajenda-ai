from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.services.system_status_service import SystemStatusService

router = APIRouter(tags=["system"])


@router.get("/system/health", deprecated=True)
def system_health() -> JSONResponse:
    """Deprecated alias for root ``/health``. Use ``/health`` for deploy probes."""
    return JSONResponse(
        content={"status": "ok"},
        headers={
            "Deprecation": "true",
            "Link": '</health>; rel="successor-version"',
        },
    )


@router.get("/system/readiness")
def system_readiness(request: Request) -> JSONResponse:
    service = SystemStatusService(session=None)
    status_code, payload = service.readiness(
        database_runtime=getattr(request.app.state, "database_runtime", None),
        queue_adapter=getattr(request.app.state, "queue_adapter", None),
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/system/status")
def system_status(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, dict[str, int]]:
    return SystemStatusService(db).status(tenant_id=str(tenant_id))
