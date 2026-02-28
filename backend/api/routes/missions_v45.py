"""
Missions API Routes (v4.5 - Fully Functional)

Built with Pride for Obex Blackvault
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime

from backend.middleware.auth.auth_middleware import get_current_user
from backend.orchestration.mission_executor import MissionExecutor
from backend.economy.resource_marketplace import ResourceMarketplace
from backend.core.event_bus.nats_bus import NATSEventBus
from backend.integrations.llm.llm_factory import LLMFactory
from backend.database.session import get_db
from backend.database.models import Mission
from backend.models.domain.user import User

router = APIRouter(prefix="/api/v1/missions", tags=["missions"])

# Dependency injection
_executor: Optional[MissionExecutor] = None


def get_mission_executor() -> MissionExecutor:
    """Get or create mission executor singleton"""
    global _executor
    if _executor is None:
        marketplace = ResourceMarketplace()
        event_bus = NATSEventBus()
        llm_factory = LLMFactory()
        _executor = MissionExecutor(marketplace, event_bus, llm_factory)
    return _executor


class CreateMissionRequest(BaseModel):
    """Request to create a new mission"""

    name: str = Field(..., description="Human-readable mission name")
    goal: str = Field(..., description="Mission objective in natural language")
    budget: Optional[float] = Field(None, description="Budget limit in credits")
    priority: Optional[int] = Field(1, description="Priority level (1-10)")


class MissionResponse(BaseModel):
    """Mission execution response"""

    mission_id: str
    status: str
    message: Optional[str] = None
    output: Optional[str] = None
    cost: Optional[float] = None
    duration_seconds: Optional[float] = None
    agents_used: Optional[List[str]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


def _mission_to_response(mission: Mission) -> MissionResponse:
    """
    Convert a :class:`Mission` ORM object to a :class:`MissionResponse`.

    Args:
        mission: SQLAlchemy Mission instance.

    Returns:
        Populated MissionResponse.
    """
    result_data = mission.result or {}
    output = result_data.get("output") if isinstance(result_data, dict) else None
    agents_used = (
        result_data.get("agents_used") if isinstance(result_data, dict) else None
    )

    duration: Optional[float] = None
    if mission.started_at and mission.completed_at:
        duration = (mission.completed_at - mission.started_at).total_seconds()
    elif mission.execution_time is not None:
        duration = mission.execution_time

    return MissionResponse(
        mission_id=mission.id,
        status=mission.status,
        message=mission.error if mission.error else None,
        output=output,
        cost=mission.cost,
        duration_seconds=duration,
        agents_used=agents_used,
        created_at=mission.created_at,
    )


@router.post("/", response_model=MissionResponse)
async def create_mission(
    request: CreateMissionRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    executor: MissionExecutor = Depends(get_mission_executor),
):
    """
    Create and execute a new mission.

    This endpoint:
    1. Validates the mission with Guardian
    2. Creates an execution plan with Commander
    3. Executes the mission with appropriate agents
    4. Archives the results with Archivist
    5. Distributes rewards through the Agent Economy
    """
    import uuid

    mission_id = str(uuid.uuid4())

    result = await executor.execute_mission(
        mission_id=mission_id,
        goal=request.goal,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        budget=request.budget,
    )

    return MissionResponse(
        mission_id=mission_id,
        status=result["status"],
        message=f"Mission '{request.name}' completed",
        output=result.get("output"),
        cost=result.get("cost"),
        duration_seconds=result.get("duration_seconds"),
        agents_used=result.get("agents_used"),
    )


@router.get("/{mission_id}", response_model=MissionResponse)
async def get_mission(
    mission_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve mission status and results by ID.

    Returns the mission record for the authenticated tenant.  Raises 404 if
    the mission does not exist or belongs to a different tenant.
    """
    mission: Optional[Mission] = (
        db.query(Mission)
        .filter(
            Mission.id == mission_id,
            Mission.tenant_id == current_user.tenant_id,
        )
        .first()
    )

    if mission is None:
        raise HTTPException(
            status_code=404,
            detail=f"Mission '{mission_id}' not found",
        )

    return _mission_to_response(mission)


@router.get("/", response_model=List[MissionResponse])
async def list_missions(
    limit: int = Query(
        default=50, ge=1, le=200, description="Maximum results to return"
    ),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all missions for the current tenant.

    Supports pagination via ``limit`` / ``offset`` and optional status
    filtering.  Results are ordered by creation date descending (newest
    first).
    """
    query = db.query(Mission).filter(Mission.tenant_id == current_user.tenant_id)

    if status:
        query = query.filter(Mission.status == status.upper())

    missions: List[Mission] = (
        query.order_by(Mission.created_at.desc()).offset(offset).limit(limit).all()
    )

    return [_mission_to_response(m) for m in missions]
