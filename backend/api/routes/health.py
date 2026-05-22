from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.services.system_status_service import SystemStatusService

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readiness")
def readiness(request: Request) -> JSONResponse:
    service = SystemStatusService(session=None)
    status_code, payload = service.readiness(
        database_runtime=getattr(request.app.state, "database_runtime", None),
        queue_adapter=getattr(request.app.state, "queue_adapter", None),
    )
    return JSONResponse(status_code=status_code, content=payload)
