from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.services.branch_manager import BranchManager

router = APIRouter(prefix="/branches", tags=["branches"])


class BranchCreateRequest(BaseModel):
    mission_id: UUID
    parent_branch_id: UUID | None = None
    reason: str


@router.post("")
def create_branch(
    body: BranchCreateRequest,
    tenant_id: str = Header(alias="X-Tenant-Id"),
    db: Session = Depends(get_db_session),
) -> dict[str, str]:
    manager = BranchManager(db)
    branch = manager.create_branch(
        tenant_id=tenant_id,
        mission_id=body.mission_id,
        parent_branch_id=body.parent_branch_id,
        reason=body.reason,
    )
    return {"branch_id": str(branch.id), "state": branch.status}
