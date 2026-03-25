"""
Workforces API Routes — Phase 4: The Coordinating Agent (v6.3)

Provides full CRUD for Workforce configurations and the ability to run
a coordinated multi-agent mission against a workforce.

Endpoints:
  POST   /api/v1/workforces                          Create a workforce
  GET    /api/v1/workforces                          List workforces (tenant-scoped)
  GET    /api/v1/workforces/{id}                     Get a workforce
  PATCH  /api/v1/workforces/{id}                     Update a workforce
  DELETE /api/v1/workforces/{id}                     Delete a workforce
  POST   /api/v1/workforces/{id}/members             Add a member
  DELETE /api/v1/workforces/{id}/members/{member_id} Remove a member
  POST   /api/v1/workforces/{id}/run                 Run a coordinated mission
  GET    /api/v1/workforces/{id}/runs/{run_id}       Get run status

Built with Pride for Obex Blackvault.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.routes.auth import get_current_user
from backend.database import get_db
from backend.database.models import Agent, Workforce, WorkforceMember

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/workforces", tags=["workforces"])


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------


def _get_workforce_coordinator():
    """Lazy import to avoid circular dependency at module load time."""
    try:
        from backend.main import get_workforce_coordinator

        return get_workforce_coordinator()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class WorkforceRoleConfig(BaseModel):
    """A single role entry in a workforce configuration."""

    role: str = Field(..., description="AgentRole value (e.g. 'researcher')")


class WorkforceCreate(BaseModel):
    """Schema for creating a new workforce."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    roles: List[WorkforceRoleConfig] = Field(
        default_factory=lambda: [
            WorkforceRoleConfig(role="researcher"),
            WorkforceRoleConfig(role="analyst"),
            WorkforceRoleConfig(role="writer"),
        ]
    )
    pipeline_type: str = Field(
        default="sequential",
        pattern="^(sequential|parallel|mixed)$",
    )
    default_budget: Optional[float] = Field(None, ge=0.0)


class WorkforceUpdate(BaseModel):
    """Schema for updating a workforce."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    roles: Optional[List[WorkforceRoleConfig]] = None
    pipeline_type: Optional[str] = Field(None, pattern="^(sequential|parallel|mixed)$")
    default_budget: Optional[float] = Field(None, ge=0.0)
    is_active: Optional[bool] = None


class WorkforceMemberCreate(BaseModel):
    """Schema for adding a member to a workforce."""

    agent_id: str = Field(..., description="Agent ID to assign")
    role: str = Field(..., description="AgentRole value")
    priority: int = Field(default=0, ge=0, le=100)


class WorkforceRunRequest(BaseModel):
    """Schema for running a coordinated mission."""

    goal: str = Field(..., min_length=1, max_length=4000, description="Mission goal")
    pipeline_type: Optional[str] = Field(None, pattern="^(sequential|parallel|mixed)$")
    budget: Optional[float] = Field(None, ge=0.0)


class WorkforceMemberResponse(BaseModel):
    """Workforce member response model."""

    id: str
    workforce_id: str
    agent_id: str
    role: str
    priority: int
    is_active: bool
    created_at: str


class WorkforceResponse(BaseModel):
    """Workforce response model."""

    id: str
    name: str
    description: Optional[str]
    tenant_id: str
    roles: List[Dict[str, Any]]
    pipeline_type: str
    default_budget: Optional[float]
    is_active: bool
    total_runs: int
    successful_runs: int
    failed_runs: int
    created_at: str
    updated_at: str
    last_run_at: Optional[str]
    members: List[WorkforceMemberResponse]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _workforce_to_response(wf: Workforce) -> WorkforceResponse:
    """Convert a Workforce ORM object to a WorkforceResponse."""
    members = [
        WorkforceMemberResponse(
            id=m.id,
            workforce_id=m.workforce_id,
            agent_id=m.agent_id,
            role=m.role,
            priority=m.priority,
            is_active=m.is_active,
            created_at=m.created_at.isoformat(),
        )
        for m in (wf.members or [])
        if m.is_active
    ]
    return WorkforceResponse(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        tenant_id=wf.tenant_id,
        roles=wf.roles or [],
        pipeline_type=wf.pipeline_type,
        default_budget=wf.default_budget,
        is_active=wf.is_active,
        total_runs=wf.total_runs,
        successful_runs=wf.successful_runs,
        failed_runs=wf.failed_runs,
        created_at=wf.created_at.isoformat(),
        updated_at=wf.updated_at.isoformat(),
        last_run_at=wf.last_run_at.isoformat() if wf.last_run_at else None,
        members=members,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WorkforceResponse)
async def create_workforce(
    payload: WorkforceCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkforceResponse:
    """
    Create a new workforce configuration.

    The workforce defines which agent roles participate and in what order.
    Members (specific agents assigned to roles) can be added separately.
    """
    wf = Workforce(
        id=f"wf_{uuid.uuid4().hex[:16]}",
        name=payload.name,
        description=payload.description,
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        roles=[r.dict() for r in payload.roles],
        pipeline_type=payload.pipeline_type,
        default_budget=payload.default_budget,
        is_active=True,
        total_runs=0,
        successful_runs=0,
        failed_runs=0,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)

    logger.info(f"Workforce created: {wf.id} by user {current_user.id}")
    return _workforce_to_response(wf)


@router.get("", response_model=List[WorkforceResponse])
async def list_workforces(
    include_inactive: bool = False,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[WorkforceResponse]:
    """List all workforces for the current tenant."""
    query = db.query(Workforce).filter(Workforce.tenant_id == current_user.tenant_id)
    if not include_inactive:
        query = query.filter(Workforce.is_active.is_(True))

    workforces = query.order_by(Workforce.created_at.desc()).all()
    return [_workforce_to_response(wf) for wf in workforces]


@router.get("/{workforce_id}", response_model=WorkforceResponse)
async def get_workforce(
    workforce_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkforceResponse:
    """Get a specific workforce by ID."""
    wf = (
        db.query(Workforce)
        .filter(
            Workforce.id == workforce_id,
            Workforce.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workforce {workforce_id} not found",
        )
    return _workforce_to_response(wf)


@router.patch("/{workforce_id}", response_model=WorkforceResponse)
async def update_workforce(
    workforce_id: str,
    payload: WorkforceUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkforceResponse:
    """Update a workforce configuration."""
    wf = (
        db.query(Workforce)
        .filter(
            Workforce.id == workforce_id,
            Workforce.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workforce {workforce_id} not found",
        )

    update_data = payload.dict(exclude_unset=True)
    if "roles" in update_data:
        update_data["roles"] = [r.dict() for r in payload.roles]

    for field_name, value in update_data.items():
        setattr(wf, field_name, value)
    wf.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(wf)
    return _workforce_to_response(wf)


@router.delete("/{workforce_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workforce(
    workforce_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Soft-delete a workforce (sets is_active=False)."""
    wf = (
        db.query(Workforce)
        .filter(
            Workforce.id == workforce_id,
            Workforce.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workforce {workforce_id} not found",
        )
    wf.is_active = False
    wf.updated_at = datetime.utcnow()
    db.commit()


@router.post(
    "/{workforce_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkforceMemberResponse,
)
async def add_member(
    workforce_id: str,
    payload: WorkforceMemberCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkforceMemberResponse:
    """Assign an agent to a role within a workforce."""
    wf = (
        db.query(Workforce)
        .filter(
            Workforce.id == workforce_id,
            Workforce.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workforce {workforce_id} not found",
        )

    # Verify agent belongs to the same tenant
    agent = (
        db.query(Agent)
        .filter(
            Agent.id == payload.agent_id,
            Agent.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {payload.agent_id} not found",
        )

    member = WorkforceMember(
        id=f"wfm_{uuid.uuid4().hex[:16]}",
        workforce_id=workforce_id,
        agent_id=payload.agent_id,
        role=payload.role,
        priority=payload.priority,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(member)
    db.commit()
    db.refresh(member)

    return WorkforceMemberResponse(
        id=member.id,
        workforce_id=member.workforce_id,
        agent_id=member.agent_id,
        role=member.role,
        priority=member.priority,
        is_active=member.is_active,
        created_at=member.created_at.isoformat(),
    )


@router.delete(
    "/{workforce_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    workforce_id: str,
    member_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Remove a member from a workforce (soft-delete)."""
    member = (
        db.query(WorkforceMember)
        .filter(
            WorkforceMember.id == member_id,
            WorkforceMember.workforce_id == workforce_id,
        )
        .first()
    )
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Member {member_id} not found in workforce {workforce_id}",
        )
    member.is_active = False
    db.commit()


@router.post("/{workforce_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_workforce(
    workforce_id: str,
    payload: WorkforceRunRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Run a coordinated multi-agent mission against a workforce.

    Transitional behavior:
    - returns the real coordinator-issued run_id
    - keeps current in-memory run tracking runnable
    - governed execution state is exposed via get_run_state()
    """
    wf = (
        db.query(Workforce)
        .filter(
            Workforce.id == workforce_id,
            Workforce.tenant_id == current_user.tenant_id,
            Workforce.is_active.is_(True),
        )
        .first()
    )
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workforce {workforce_id} not found or inactive",
        )

    coordinator = _get_workforce_coordinator()
    if not coordinator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WorkforceCoordinator is not available",
        )

    roles = [r.get("role") for r in (wf.roles or []) if r.get("role")]
    pipeline_type = payload.pipeline_type or wf.pipeline_type
    budget = payload.budget or wf.default_budget

    wf.total_runs += 1
    wf.last_run_at = datetime.utcnow()
    wf.updated_at = datetime.utcnow()
    db.commit()

    result = await coordinator.run(
        workforce_id=workforce_id,
        goal=payload.goal,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        roles=roles,
        pipeline_type=pipeline_type,
        budget=budget,
    )

    try:
        wf_db = db.query(Workforce).filter(Workforce.id == workforce_id).first()
        if wf_db:
            if result.get("status") in ("completed",):
                wf_db.successful_runs += 1
            else:
                wf_db.failed_runs += 1
            db.commit()
    except Exception as exc:
        logger.warning(f"Failed to update workforce run stats: {exc}")

    return {
        "message": "Workforce run started",
        "workforce_id": workforce_id,
        "run_id": result["run_id"],
        "goal": payload.goal,
        "roles": roles,
        "pipeline_type": pipeline_type,
        "status": result.get("status", "running"),
    }


@router.get("/{workforce_id}/runs/{run_id}")
async def get_run_status(
    workforce_id: str,
    run_id: str,
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get the status of a workforce run.

    Transitional behavior:
    - governed execution_tasks / governed_execution_state are the primary runtime view
    - legacy_sub_missions / sub_missions remain for compatibility only
    - coordinator.get_run_state() remains the runtime read seam
    """
    coordinator = _get_workforce_coordinator()
    if not coordinator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WorkforceCoordinator is not available",
        )

    run = coordinator.get_run_state(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )

    if run.get("workforce_id") != workforce_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found in workforce {workforce_id}",
        )

    if run.get("tenant_id") != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Response is intentionally governed-first:
    # - execution_tasks / governed_execution_state are primary
    # - legacy_sub_missions / sub_missions are compatibility payloads
    return run
