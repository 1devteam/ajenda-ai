from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from backend.services.system_status_service import SystemStatusService

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readiness")
def readiness(request: Request, response: Response) -> dict[str, object]:
    service = SystemStatusService(session=None)
    payload = service.readiness(
        database_runtime=request.app.state.database_runtime,
        queue_adapter=request.app.state.queue_adapter,
    )
    if payload["status"] != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload
