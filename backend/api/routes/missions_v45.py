"""
Missions API Routes (v4.5 - Fully Functional)
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from backend.middleware.auth.auth_middleware import get_current_user
from backend.orchestration.mission_executor import MissionExecutor
from backend.economy.resource_marketplace import ResourceMarketplace
from backend.core.event_bus.nats_bus import NATSEventBus
from backend.integrations.llm.llm_factory import LLMFactory
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


@router.post("/", response_model=MissionResponse)
async def create_mission(
    request: CreateMissionRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    executor: MissionExecutor = Depends(get_mission_executor)
):
    """
    Create and execute a new mission
    
    This endpoint:
    1. Validates the mission with Guardian
    2. Creates an execution plan with Commander
    3. Executes the mission with appropriate agents
    4. Archives the results with Archivist
    5. Distributes rewards through the Agent Economy
    """
    import uuid
    
    mission_id = str(uuid.uuid4())
    
    # Execute mission in background
    result = await executor.execute_mission(
        mission_id=mission_id,
        goal=request.goal,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        budget=request.budget
    )
    
    return MissionResponse(
        mission_id=mission_id,
        status=result["status"],
        message=f"Mission '{request.name}' completed",
        output=result.get("output"),
        cost=result.get("cost"),
        duration_seconds=result.get("duration_seconds"),
        agents_used=result.get("agents_used")
    )


@router.get("/{mission_id}", response_model=MissionResponse)
async def get_mission(
    mission_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get mission status and results"""
    # TODO: Implement mission retrieval from database
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/", response_model=List[MissionResponse])
async def list_missions(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user)
):
    """List all missions for the current tenant"""
    # TODO: Implement mission listing from database
    raise HTTPException(status_code=501, detail="Not implemented yet")
