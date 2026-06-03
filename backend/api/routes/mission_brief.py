from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.services.mission_brief import MissionBriefRead, MissionBriefRequest, build_mission_brief

router = APIRouter(prefix="/mission-brief", tags=["mission-brief"])


@router.post("/draft", response_model=MissionBriefRead)
def draft_mission_brief(
    body: MissionBriefRequest,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionBriefRead:
    """Draft a read-only Mission Brief from approved Business Profile facts and current intent.

    This endpoint is a read-model/declarative contract only. It must not create
    missions, mission plans, task graphs, execution tasks, queue messages,
    worker leases, evidence/outcome/retrieval records, durable profile truth, or
    memory-promotion records.
    """
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_READ, tenant_id=tenant_id)
    profile = BusinessProfileRepository(db).get_active_profile_for_tenant(tenant_id=str(tenant_id))
    return build_mission_brief(tenant_id=str(tenant_id), profile=profile, request=body)
