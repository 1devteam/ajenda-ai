from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.errors import quota_exceeded_http
from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.repositories.mission_repository import MissionRepository
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError
from backend.services.workforce_provisioner import WorkforceProvisioner

router = APIRouter(prefix="/workforces", tags=["workforces"])


class AgentSpec(BaseModel):
    display_name: str = Field(min_length=1)
    role_name: str = Field(min_length=1)


class ProvisionFleetRequest(BaseModel):
    mission_id: str
    fleet_name: str = Field(min_length=1)
    agents: list[AgentSpec]


@router.post("/provision")
def provision_workforce(
    body: ProvisionFleetRequest,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, str]:
    """Provision a workforce fleet for a tenant-owned mission.

    Authorization and tenant ownership are verified before consuming quota so
    unauthorized, missing, or foreign missions cannot mutate tenant usage.
    """
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.PROVISION_WORKFORCE,
        tenant_id=tenant_id,
    )

    try:
        mission_id = _uuid.UUID(body.mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="mission_id must be a valid UUID") from exc

    tenant_id_str = str(tenant_id)
    if MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str) is None:
        raise HTTPException(status_code=400, detail="mission not found for tenant")

    agents_requested = len(body.agents)

    # --- Quota check: agents per fleet ---
    try:
        QuotaEnforcementService(db).check_and_record_agent_provisioning(
            tenant_id,
            agents_requested=agents_requested,
        )
    except QuotaExceededError as exc:
        raise quota_exceeded_http(exc) from exc

    provisioner = WorkforceProvisioner(db)
    fleet = provisioner.provision_fleet(
        tenant_id=tenant_id_str,
        mission_id=mission_id,
        fleet_name=body.fleet_name,
        agent_specs=[(spec.display_name, spec.role_name) for spec in body.agents],
    )
    return {"fleet_id": str(fleet.id), "state": fleet.status}
