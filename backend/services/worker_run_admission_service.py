from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.queue.base import QueueAdapter


class WorkerRunAdmissionService:
    """Compatibility tombstone for the removed synchronous HTTP run spine.

    Production execution is owned exclusively by ``WorkerLoop`` and
    ``WorkerRuntimeService``. Keeping a fail-closed class avoids import-time
    breakage for older integrations without retaining claim or dispatch power.
    """

    def __init__(self, db: Session, queue: QueueAdapter, **_: Any) -> None:
        self._db = db
        self._queue = queue

    def admit(self, *, mission_id: UUID, tenant_id: UUID, admitted_by: str, request: Any) -> Any:
        del mission_id, tenant_id, admitted_by, request
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="HTTP worker run admission was removed; use the daemon worker runtime.",
        )
