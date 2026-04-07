from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
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
    """Provision a workforce fleet for a mission.

    Enforces per-fleet agent count quota before provisioning. Returns HTTP 429
    with a structured body if the tenant has reached their plan limit.
    """
    agents_requested = len(body.agents)

    # --- Quota check: agents per fleet ---
    try:
        QuotaEnforcementService(db).check_and_record_agent_provisioning(
            tenant_id,
            agents_requested=agents_requested,
        )
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "QUOTA_EXCEEDED",
                "field": exc.field,
                "limit": exc.limit,
                "current": exc.current,
                "plan": exc.plan,
                "message": (
                    f"You have reached the {exc.field} limit ({exc.limit}) "
                    f"for the {exc.plan!r} plan. Upgrade to continue."
                ),
            },
        ) from exc

    provisioner = WorkforceProvisioner(db)
    fleet = provisioner.provision_fleet(
        tenant_id=str(tenant_id),
        mission_id=_uuid.UUID(body.mission_id),
        fleet_name=body.fleet_name,
        agent_specs=[(spec.display_name, spec.role_name) for spec in body.agents],
    )
    return {"fleet_id": str(fleet.id), "state": fleet.status}
