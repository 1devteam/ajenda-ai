from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readiness")
def readiness(db: Session = Depends(get_db_session)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}
