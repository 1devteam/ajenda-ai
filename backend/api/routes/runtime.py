from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.services.runtime_governor import RuntimeGovernor

router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/mode")
def get_runtime_mode(db: Session = Depends(get_db_session)) -> dict[str, str | bool]:
    decision = RuntimeGovernor(db).evaluate()
    return {
        "mode": decision.mode.value,
        "provisioning_allowed": decision.provisioning_allowed,
        "execution_allowed": decision.execution_allowed,
        "reason": decision.reason,
    }
