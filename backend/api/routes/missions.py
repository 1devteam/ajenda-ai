"""
Missions API Routes
Handles mission management and execution

Built with Pride for Obex Blackvault
"""
from fastapi import APIRouter, HTTPException, status, Query, Depends
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

from backend.models.domain.mission import MissionStatus, MissionPriority

# Import authentication dependency
from backend.api.routes.auth import get_current_user

router = APIRouter(prefix="/api/v1/missions", tags=["missions"])


# ============================================================================
# Request/Response Models
# ============================================================================

class MissionCreate(BaseModel):
    """Schema for creating a new mission (supports both v4.5 and v5.0 formats)"""
    # v5.0 fields
    objective: Optional[str] = Field(None, min_length=1, description="Mission objective")
    agent_id: str = Field(..., description="Agent ID to execute the mission")
    priority: MissionPriority = Field(default=MissionPriority.NORMAL, description="Mission priority")
    context: Dict[str, Any] = Field(default_factory=dict, description="Mission context")
    max_steps: int = Field(default=10, ge=1, le=100, description="Maximum execution steps")
    timeout_seconds: int = Field(default=300, ge=1, description="Execution timeout in seconds")

    # v4.5 backward compatibility fields
    command: Optional[str] = Field(None, description="[v4.5] Mission command")
    message: Optional[str] = Field(None, description="[v4.5] Mission message")
    payload: Optional[str] = Field(None, description="[v4.5] Mission payload (JSON string)")
    state: Optional[str] = Field(None, description="[v4.5] Initial state")


class MissionUpdate(BaseModel):
    """Schema for updating a mission"""
    status: Optional[MissionStatus] = None
    priority: Optional[MissionPriority] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class MissionResponse(BaseModel):
    """Mission response model"""
    id: str
    objective: str
    status: str
    priority: str
    agent_id: str
    tenant_id: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    steps: List[Dict[str, Any]] = []
    context: Dict[str, Any]
    max_steps: int
    timeout_seconds: int
    execution_time: Optional[float] = None
    tokens_used: int = 0
    cost: float = 0.0


class MissionExecuteRequest(BaseModel):
    """Request to execute a mission"""
    input: Optional[str] = Field(None, description="Additional input for execution")


class MissionExecuteResponse(BaseModel):
    """Response from mission execution"""
    mission_id: str
    status: str
    output: Optional[str] = None
    error: Optional[str] = None
    execution_time: float
    tokens_used: int
    cost: float


# ============================================================================
# In-Memory Storage (Replace with database in production)
# ============================================================================

_missions_db: dict[str, dict] = {}


# ============================================================================
# Helper Functions
# ============================================================================

def _update_agent_stats(agent_id: str, success: bool):
    """Update agent mission statistics"""
    # Import here to avoid circular dependency
    from backend.api.routes.agents import _agents_db

    if agent_id in _agents_db:
        agent = _agents_db[agent_id]
        agent["total_missions"] += 1
        if success:
            agent["successful_missions"] += 1
        else:
            agent["failed_missions"] += 1
        agent["last_active"] = datetime.utcnow()


# ============================================================================
# API Endpoints (ALL PROTECTED WITH AUTHENTICATION)
# ============================================================================

@router.post("", response_model=MissionResponse, status_code=status.HTTP_201_CREATED)
async def create_mission(
    mission: MissionCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new mission
    
    Creates a new mission for an agent to execute.
    Mission will be created under the authenticated user's tenant.
    Agent must belong to the same tenant.
    """
    # Verify agent exists and belongs to user's tenant
    from backend.api.routes.agents import _agents_db
    
    if mission.agent_id not in _agents_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {mission.agent_id} not found"
        )
    
    agent = _agents_db[mission.agent_id]
    
    # Enforce tenant isolation - can only create missions for own agents
    if agent["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant"
        )

    mission_id = f"mission_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow()

    # Handle v4.5 backward compatibility
    objective = mission.objective
    context = mission.context

    if not objective and mission.message:
        # v4.5 format: use message as objective
        objective = mission.message

    if mission.payload:
        # v4.5 format: parse payload into context
        try:
            import json
            context = json.loads(mission.payload) if isinstance(mission.payload, str) else mission.payload
        except:
            context = {"payload": mission.payload}

    # Use authenticated user's tenant_id
    tenant_id = current_user["tenant_id"]

    mission_data = {
        "id": mission_id,
        "objective": objective or "No objective specified",
        "status": MissionStatus.PENDING.value,
        "priority": mission.priority.value if isinstance(mission.priority, MissionPriority) else mission.priority,
        "agent_id": mission.agent_id,
        "tenant_id": tenant_id,
        "created_at": now,
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
        "steps": [],
        "context": context,
        "max_steps": mission.max_steps,
        "timeout_seconds": mission.timeout_seconds,
        "execution_time": None,
        "tokens_used": 0,
        "cost": 0.0
    }

    _missions_db[mission_id] = mission_data

    return MissionResponse(**mission_data)


@router.get("/{mission_id}", response_model=MissionResponse)
async def get_mission(
    mission_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get mission by ID
    
    Retrieves a specific mission's information.
    Users can only access missions in their own tenant.
    """
    if mission_id not in _missions_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found"
        )
    
    mission = _missions_db[mission_id]
    
    # Enforce tenant isolation
    if mission["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant"
        )

    return MissionResponse(**mission)


@router.get("", response_model=List[MissionResponse])
async def list_missions(
    current_user: dict = Depends(get_current_user),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    status: Optional[MissionStatus] = Query(None, description="Filter by status"),
    priority: Optional[MissionPriority] = Query(None, description="Filter by priority"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max number of records to return")
):
    """
    List all missions
    
    Returns a list of missions with optional filtering.
    Users can only see missions in their own tenant.
    """
    # Filter by authenticated user's tenant only
    user_tenant_id = current_user["tenant_id"]
    missions = [m for m in _missions_db.values() if m["tenant_id"] == user_tenant_id]

    # Apply additional filters
    if agent_id:
        missions = [m for m in missions if m["agent_id"] == agent_id]

    if status:
        status_value = status.value if isinstance(status, MissionStatus) else status
        missions = [m for m in missions if m["status"] == status_value]

    if priority:
        priority_value = priority.value if isinstance(priority, MissionPriority) else priority
        missions = [m for m in missions if m["priority"] == priority_value]

    # Sort by created_at descending (newest first)
    missions.sort(key=lambda m: m["created_at"], reverse=True)

    # Apply pagination
    missions = missions[skip:skip + limit]

    return [MissionResponse(**m) for m in missions]


@router.put("/{mission_id}", response_model=MissionResponse)
async def update_mission(
    mission_id: str,
    mission: MissionUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Update mission
    
    Updates a mission's status or result.
    Users can only update missions in their own tenant.
    """
    if mission_id not in _missions_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found"
        )

    mission_data = _missions_db[mission_id]
    
    # Enforce tenant isolation
    if mission_data["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant"
        )

    # Update fields if provided
    if mission.status is not None:
        mission_data["status"] = mission.status.value if isinstance(mission.status, MissionStatus) else mission.status
    if mission.priority is not None:
        mission_data["priority"] = mission.priority.value if isinstance(mission.priority, MissionPriority) else mission.priority
    if mission.result is not None:
        mission_data["result"] = mission.result
    if mission.error is not None:
        mission_data["error"] = mission.error

    return MissionResponse(**mission_data)


@router.delete("/{mission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mission(
    mission_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete mission
    
    Deletes a mission from the system.
    Users can only delete missions in their own tenant.
    """
    if mission_id not in _missions_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found"
        )
    
    mission = _missions_db[mission_id]
    
    # Enforce tenant isolation
    if mission["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant"
        )

    del _missions_db[mission_id]
    return None


@router.post("/{mission_id}/start", response_model=MissionResponse)
async def start_mission(
    mission_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Start mission execution
    
    Begins executing a pending mission.
    Users can only start missions in their own tenant.
    """
    if mission_id not in _missions_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found"
        )

    mission_data = _missions_db[mission_id]
    
    # Enforce tenant isolation
    if mission_data["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant"
        )

    if mission_data["status"] != MissionStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mission is not in PENDING status (current: {mission_data['status']})"
        )

    mission_data["status"] = MissionStatus.RUNNING.value
    mission_data["started_at"] = datetime.utcnow()

    # Update agent status
    from backend.api.routes.agents import _agents_db
    agent_id = mission_data["agent_id"]
    if agent_id in _agents_db:
        _agents_db[agent_id]["status"] = "busy"

    return MissionResponse(**mission_data)


@router.post("/{mission_id}/complete", response_model=MissionResponse)
async def complete_mission(
    mission_id: str,
    result: Dict[str, Any],
    current_user: dict = Depends(get_current_user)
):
    """
    Complete mission execution
    
    Marks a mission as completed with results.
    Users can only complete missions in their own tenant.
    """
    if mission_id not in _missions_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found"
        )

    mission_data = _missions_db[mission_id]
    
    # Enforce tenant isolation
    if mission_data["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant"
        )

    if mission_data["status"] != MissionStatus.RUNNING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mission is not in RUNNING status (current: {mission_data['status']})"
        )

    now = datetime.utcnow()
    mission_data["status"] = MissionStatus.COMPLETED.value
    mission_data["completed_at"] = now
    mission_data["result"] = result

    # Calculate execution time
    if mission_data["started_at"]:
        mission_data["execution_time"] = (now - mission_data["started_at"]).total_seconds()

    # Update agent stats and status
    _update_agent_stats(mission_data["agent_id"], success=True)
    from backend.api.routes.agents import _agents_db
    agent_id = mission_data["agent_id"]
    if agent_id in _agents_db:
        _agents_db[agent_id]["status"] = "idle"

    return MissionResponse(**mission_data)


@router.post("/{mission_id}/fail", response_model=MissionResponse)
async def fail_mission(
    mission_id: str,
    error: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Fail mission execution
    
    Marks a mission as failed with error details.
    Users can only fail missions in their own tenant.
    """
    if mission_id not in _missions_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found"
        )

    mission_data = _missions_db[mission_id]
    
    # Enforce tenant isolation
    if mission_data["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant"
        )

    now = datetime.utcnow()
    mission_data["status"] = MissionStatus.FAILED.value
    mission_data["completed_at"] = now
    mission_data["error"] = error

    # Calculate execution time
    if mission_data["started_at"]:
        mission_data["execution_time"] = (now - mission_data["started_at"]).total_seconds()

    # Update agent stats and status
    _update_agent_stats(mission_data["agent_id"], success=False)
    from backend.api.routes.agents import _agents_db
    agent_id = mission_data["agent_id"]
    if agent_id in _agents_db:
        _agents_db[agent_id]["status"] = "idle"

    return MissionResponse(**mission_data)


@router.post("/{mission_id}/cancel", response_model=MissionResponse)
async def cancel_mission(
    mission_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Cancel mission execution
    
    Cancels a pending or running mission.
    Users can only cancel missions in their own tenant.
    """
    if mission_id not in _missions_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found"
        )

    mission_data = _missions_db[mission_id]
    
    # Enforce tenant isolation
    if mission_data["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant"
        )

    if mission_data["status"] in [MissionStatus.COMPLETED.value, MissionStatus.FAILED.value]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel mission in {mission_data['status']} status"
        )

    mission_data["status"] = MissionStatus.CANCELLED.value
    mission_data["completed_at"] = datetime.utcnow()

    # Update agent status
    from backend.api.routes.agents import _agents_db
    agent_id = mission_data["agent_id"]
    if agent_id in _agents_db:
        _agents_db[agent_id]["status"] = "idle"

    return MissionResponse(**mission_data)
