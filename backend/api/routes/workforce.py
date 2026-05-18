from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError
from backend.services.workforce_provisioner import WorkforceProvisioner

router = APIRouter(prefix="/workforces", tags=["workforces"])

_REQUEST_TENANT_ID = Depends(get_request_tenant_id)
_TENANT_DB_SESSION = Depends(get_tenant_db_session)


class AgentSpec(BaseModel):
    display_name: str = Field(min_length=1)
    role_name: str = Field(min_length=1)


class ProvisionFleetRequest(BaseModel):
    mission_id: str
    fleet_name: str = Field(min_length=1)
    agents: list[AgentSpec]


def _tenant_uuid_or_400(tenant_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-Id must be a UUID") from exc


def _quota_detail(exc: QuotaExceededError) -> dict[str, Any]:
    return {
        "code": "QUOTA_EXCEEDED",
        "field": exc.field,
        "limit": exc.limit,
        "current": exc.current,
        "plan": exc.plan,
    }


@router.post("/provision")
def provision_workforce(
    body: ProvisionFleetRequest,
    tenant_id: str = _REQUEST_TENANT_ID,
    db: Session = _TENANT_DB_SESSION,
) -> dict[str, str]:
    try:
        QuotaEnforcementService(db).check_and_record_agent_provisioning(
            _tenant_uuid_or_400(tenant_id),
            agents_requested=len(body.agents),
        )
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=_quota_detail(exc)) from exc

    provisioner = WorkforceProvisioner(db)
    fleet = provisioner.provision_fleet(
        tenant_id=tenant_id,
        mission_id=uuid.UUID(body.mission_id),
        fleet_name=body.fleet_name,
        agent_specs=[(spec.display_name, spec.role_name) for spec in body.agents],
    )
    return {"fleet_id": str(fleet.id), "state": fleet.status}
