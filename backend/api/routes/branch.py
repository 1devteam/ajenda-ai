from __future__ import annotations

import uuid as _uuid
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.services.branch_manager import BranchManager

router = APIRouter(prefix="/branches", tags=["branches"])


class BranchCreateRequest(BaseModel):
    mission_id: UUID
    parent_branch_id: UUID | None = None
    reason: str


@router.post("")
def create_branch(
    body: BranchCreateRequest,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, str]:
    manager = BranchManager(db)
    branch = manager.create_branch(
        tenant_id=str(tenant_id),
        mission_id=body.mission_id,
        parent_branch_id=body.parent_branch_id,
        reason=body.reason,
    )
    return {"branch_id": str(branch.id), "state": branch.status}
