from __future__ import annotations

from fastapi import APIRouter, Request, Response
from starlette import status

from backend.services.system_status_service import SystemStatusService

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return SystemStatusService().health()


@router.get("/readiness")
def readiness(request: Request, response: Response) -> dict[str, object]:
    status_code, payload = SystemStatusService().readiness(
        database_runtime=getattr(request.app.state, "database_runtime", None),
        queue_adapter=getattr(request.app.state, "queue_adapter", None),
    )
    response.status_code = status_code if status_code == status.HTTP_200_OK else status.HTTP_503_SERVICE_UNAVAILABLE
    return payload
