from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session


class WorkerClaimAdmissionService:
    """Fail-closed compatibility tombstone for removed HTTP claim authority."""

    def __init__(self, db: Session, **_: Any) -> None:
        self._db = db

    def admit(self, *, mission_id: UUID, tenant_id: UUID, admitted_by: str) -> Any:
        del mission_id, tenant_id, admitted_by
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="HTTP worker claim admission was removed; use the daemon worker runtime.",
        )
