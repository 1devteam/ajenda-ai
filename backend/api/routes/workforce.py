from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
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
    tenant_id: str = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, str]:
    provisioner = WorkforceProvisioner(db)
    fleet = provisioner.provision_fleet(
        tenant_id=tenant_id,
        mission_id=__import__("uuid").UUID(body.mission_id),
        fleet_name=body.fleet_name,
        agent_specs=[(spec.display_name, spec.role_name) for spec in body.agents],
    )
    return {"fleet_id": str(fleet.id), "state": fleet.status}
