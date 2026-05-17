from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.queue.base import QueueAdapter
from backend.services.system_status_service import SystemStatusService

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readiness")
def readiness(
    db: Session = Depends(get_db_session),
    queue_adapter: QueueAdapter = Depends(get_queue_adapter),
) -> Any:
    readiness_status = SystemStatusService(db, queue_adapter).readiness()
    if readiness_status["dependencies"] != "ready":
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": readiness_status["database"],
                "queue": readiness_status["queue"],
            },
        )
    return {"status": "ready"}
