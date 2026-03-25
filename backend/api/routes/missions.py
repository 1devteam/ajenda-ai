"""
Missions API Routes
Handles mission management and execution
Migrated to SQLAlchemy database persistence

Built with Pride for Obex Blackvault
"""

from fastapi import APIRouter, HTTPException, status, Query, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import logging

from sqlalchemy.orm import Session
from backend.database import get_db
from backend.database.models import Mission, Agent
from backend.models.domain.mission import MissionStatus, MissionPriority

# Import authentication dependency
from backend.api.routes.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/missions", tags=["missions"])


# ============================================================================
# Request/Response Models
# ============================================================================


class MissionCreate(BaseModel):
    """Schema for creating a new mission (supports both v4.5 and v5.0 formats)"""

    # v5.0 fields
    objective: Optional[str] = Field(None, min_length=1, description="Mission objective")
    agent_id: str = Field(..., description="Agent ID to execute the mission")
    priority: MissionPriority = Field(
        default=MissionPriority.NORMAL, description="Mission priority"
    )
    context: Dict[str, Any] = Field(default_factory=dict, description="Mission context")
    max_steps: int = Field(default=10, ge=1, le=100, description="Maximum execution steps")
    timeout_seconds: int = Field(default=300, ge=1, description="Execution timeout in seconds")
    budget: Optional[float] = Field(
        None,
        gt=0,
        description="Optional credit budget cap for this mission. "
        "Execution is aborted if costs exceed this value.",
    )

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
    budget: Optional[float] = None


# ============================================================================
# Helper Functions
# ============================================================================


def _update_agent_stats(db: Session, agent_id: str, success: bool):
    """Update agent mission statistics"""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent:
        agent.total_missions += 1
        if success:
            agent.successful_missions += 1
        else:
            agent.failed_missions += 1
        agent.last_active = datetime.utcnow()
        db.commit()


def _get_execution_coordinator():
    """Lazy import to avoid circular dependency at module load time."""
    try:
        from backend.main import get_execution_coordinator

        return get_execution_coordinator()
    except Exception:
        return None


def _merge_governed_execution_state(
    mission_id: str,
    result: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Overlay authoritative governed execution state onto the legacy mission result.

    Transitional seam:
    - keeps mission.result as the API envelope
    - replaces callback-snapshot execution_state with durable governed state when available
    """
    merged_result: Dict[str, Any] = dict(result) if isinstance(result, dict) else (
        {"raw": result} if result is not None else {}
    )

    coordinator = _get_execution_coordinator()
    if not coordinator:
        return merged_result or None

    try:
        execution_state = coordinator.get_authoritative_mission_execution_state(mission_id)
    except Exception as exc:
        logger.warning(
            "Failed to load governed execution state for mission %s: %s",
            mission_id,
            exc,
        )
        return merged_result or None

    has_governed_state = any(
        execution_state.get(key) for key in ("fleets", "tasks", "branches")
    )

    if has_governed_state:
        merged_result["execution_state"] = execution_state
    elif "execution_state" not in merged_result:
        merged_result["execution_state"] = execution_state

    return merged_result or None


def _mission_to_response(mission: Mission) -> MissionResponse:
    """Convert a Mission ORM object to a MissionResponse with governed execution state."""
    return MissionResponse(
        id=mission.id,
        objective=mission.objective,
        status=mission.status,
        priority=mission.priority,
        agent_id=mission.agent_id,
        tenant_id=mission.tenant_id,
        created_at=mission.created_at,
        started_at=mission.started_at,
        completed_at=mission.completed_at,
        result=_merge_governed_execution_state(mission.id, mission.result),
        error=mission.error,
        steps=mission.steps,
        context=mission.context,
        max_steps=mission.max_steps,
        timeout_seconds=mission.timeout_seconds,
        execution_time=mission.execution_time,
        tokens_used=mission.tokens_used,
        cost=mission.cost,
        budget=mission.budget,
    )


# ============================================================================
# API Endpoints (ALL PROTECTED WITH AUTHENTICATION)
# ============================================================================


@router.post("", response_model=MissionResponse, status_code=status.HTTP_201_CREATED)
async def create_mission(
    mission: MissionCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new mission

    Creates a new mission for an agent to execute.
    Mission will be created under the authenticated user's tenant.
    Agent must belong to the same tenant.
    """
    agent = db.query(Agent).filter(Agent.id == mission.agent_id).first()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {mission.agent_id} not found",
        )

    if agent.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant",
        )

    mission_id = f"mission_{uuid.uuid4().hex[:12]}"

    objective = mission.objective
    context = mission.context

    if not objective and mission.message:
        objective = mission.message

    if mission.payload:
        try:
            import json

            context = (
                json.loads(mission.payload) if isinstance(mission.payload, str) else mission.payload
            )
        except Exception:
            context = {"payload": mission.payload}

    tenant_id = current_user["tenant_id"]

    mission_data = Mission(
        id=mission_id,
        objective=objective or "No objective specified",
        status=MissionStatus.PENDING.value,
        priority=(
            mission.priority.value
            if isinstance(mission.priority, MissionPriority)
            else mission.priority
        ),
        agent_id=mission.agent_id,
        tenant_id=tenant_id,
        created_at=datetime.utcnow(),
        context=context,
        max_steps=mission.max_steps,
        timeout_seconds=mission.timeout_seconds,
        budget=mission.budget,
        steps=[],
    )

    db.add(mission_data)
    db.commit()
    db.refresh(mission_data)

    from backend.integrations.observability.prometheus_metrics import get_metrics

    get_metrics().record_mission_created(
        complexity="unknown",
        priority=mission_data.priority,
    )

    async def execute_and_update():
        """
        Background task to execute mission and update database

        This runs asynchronously after the API returns the initial response.
        It updates the mission status in the database as execution progresses.
        """
        from backend.main import get_mission_executor
        from backend.database import SessionLocal

        try:
            executor = get_mission_executor()
        except Exception as e:
            logger.error(f"Failed to get mission executor: {e}")
            return

        async def update_status(mission_id: str, status: str, **kwargs):
            """Update mission status in database"""
            bg_db = SessionLocal()
            try:
                mission = bg_db.query(Mission).filter(Mission.id == mission_id).first()
                if mission:
                    mission.status = status

                    if status == "RUNNING":
                        if not mission.started_at:
                            mission.started_at = datetime.utcnow()
                    elif status in ["COMPLETED", "FAILED", "REJECTED"]:
                        mission.completed_at = datetime.utcnow()

                    if "result" in kwargs:
                        current_result = mission.result or {}
                        if not isinstance(current_result, dict):
                            current_result = {"raw": current_result}

                        current_result["output"] = kwargs["result"]
                        mission.result = current_result

                    elif "execution_state" in kwargs:
                        # Transitional compatibility:
                        # governed execution state is sourced authoritatively on read,
                        # so callback-only execution_state snapshots are not persisted
                        # as the primary source of truth.
                        pass

                    if "error" in kwargs:
                        mission.error = kwargs["error"]
                    if "execution_time" in kwargs:
                        mission.execution_time = kwargs["execution_time"]
                    if "cost" in kwargs:
                        mission.cost = kwargs["cost"]

                    bg_db.commit()
                    logger.info(f"Mission {mission_id} status updated to {status}")
            except Exception as e:
                logger.error(f"Failed to update mission status: {e}")
                bg_db.rollback()
            finally:
                bg_db.close()

        executor.set_status_callback(update_status)

        try:
            logger.info(f"Starting execution of mission {mission_data.id}")
            result = await executor.execute_mission(
                mission_id=mission_data.id,
                goal=mission_data.objective,
                tenant_id=mission_data.tenant_id,
                user_id=current_user["user_id"],
                budget=mission_data.budget,
            )

            bg_db = SessionLocal()
            try:
                _update_agent_stats(
                    bg_db,
                    mission_data.agent_id,
                    success=(result["status"] == "SUCCESS"),
                )
            finally:
                bg_db.close()

            logger.info(f"Mission {mission_data.id} execution completed: {result['status']}")

        except Exception as e:
            logger.error(f"Mission execution failed: {e}", exc_info=True)
            await update_status(mission_data.id, "FAILED", error=str(e))

    background_tasks.add_task(execute_and_update)
    logger.info(f"Mission {mission_data.id} created and queued for execution")

    return _mission_to_response(mission_data)


@router.get("/{mission_id}", response_model=MissionResponse)
async def get_mission(
    mission_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get mission by ID

    Retrieves a specific mission's information.
    Users can only access missions in their own tenant.
    """
    mission = db.query(Mission).filter(Mission.id == mission_id).first()

    if not mission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found",
        )

    if mission.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant",
        )

    return _mission_to_response(mission)


@router.get("", response_model=List[MissionResponse])
async def list_missions(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    status_filter: Optional[MissionStatus] = Query(
        None, alias="status", description="Filter by status"
    ),
    priority_filter: Optional[MissionPriority] = Query(
        None, alias="priority", description="Filter by priority"
    ),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max number of records to return"),
):
    """
    List all missions

    Returns a list of missions with optional filtering.
    Users can only see missions in their own tenant.
    """
    user_tenant_id = current_user["tenant_id"]
    query = db.query(Mission).filter(Mission.tenant_id == user_tenant_id)

    if agent_id:
        query = query.filter(Mission.agent_id == agent_id)

    if status_filter:
        status_value = (
            status_filter.value if isinstance(status_filter, MissionStatus) else status_filter
        )
        query = query.filter(Mission.status == status_value)

    if priority_filter:
        priority_value = (
            priority_filter.value
            if isinstance(priority_filter, MissionPriority)
            else priority_filter
        )
        query = query.filter(Mission.priority == priority_value)

    query = query.order_by(Mission.created_at.desc())
    missions = query.offset(skip).limit(limit).all()

    return [_mission_to_response(m) for m in missions]


@router.put("/{mission_id}", response_model=MissionResponse)
async def update_mission(
    mission_id: str,
    mission: MissionUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update mission

    Updates a mission's status or result.
    Users can only update missions in their own tenant.
    """
    mission_data = db.query(Mission).filter(Mission.id == mission_id).first()

    if not mission_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found",
        )

    if mission_data.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant",
        )

    if mission.status is not None:
        mission_data.status = (
            mission.status.value if isinstance(mission.status, MissionStatus) else mission.status
        )
    if mission.priority is not None:
        mission_data.priority = (
            mission.priority.value
            if isinstance(mission.priority, MissionPriority)
            else mission.priority
        )
    if mission.result is not None:
        mission_data.result = mission.result
    if mission.error is not None:
        mission_data.error = mission.error

    db.commit()
    db.refresh(mission_data)

    return _mission_to_response(mission_data)


@router.delete("/{mission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mission(
    mission_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete mission

    Deletes a mission from the system.
    Users can only delete missions in their own tenant.
    """
    mission = db.query(Mission).filter(Mission.id == mission_id).first()

    if not mission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found",
        )

    if mission.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant",
        )

    db.delete(mission)
    db.commit()
    return None


@router.post("/{mission_id}/start", response_model=MissionResponse)
async def start_mission(
    mission_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Start mission execution

    Begins executing a pending mission.
    Users can only start missions in their own tenant.
    """
    mission_data = db.query(Mission).filter(Mission.id == mission_id).first()

    if not mission_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found",
        )

    if mission_data.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant",
        )

    if mission_data.status != MissionStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mission is not in PENDING status (current: {mission_data.status})",
        )

    mission_data.status = MissionStatus.RUNNING.value
    mission_data.started_at = datetime.utcnow()

    agent = db.query(Agent).filter(Agent.id == mission_data.agent_id).first()
    if agent:
        agent.status = "busy"

    db.commit()
    db.refresh(mission_data)

    return _mission_to_response(mission_data)


@router.post("/{mission_id}/complete", response_model=MissionResponse)
async def complete_mission(
    mission_id: str,
    result: Dict[str, Any],
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Complete mission execution

    Marks a mission as completed with results.
    Users can only complete missions in their own tenant.
    """
    mission_data = db.query(Mission).filter(Mission.id == mission_id).first()

    if not mission_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found",
        )

    if mission_data.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant",
        )

    if mission_data.status != MissionStatus.RUNNING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mission is not in RUNNING status (current: {mission_data.status})",
        )

    now = datetime.utcnow()
    mission_data.status = MissionStatus.COMPLETED.value
    mission_data.completed_at = now
    mission_data.result = result

    if mission_data.started_at:
        mission_data.execution_time = (now - mission_data.started_at).total_seconds()

    _update_agent_stats(db, mission_data.agent_id, success=True)
    agent = db.query(Agent).filter(Agent.id == mission_data.agent_id).first()
    if agent:
        agent.status = "idle"

    db.commit()
    db.refresh(mission_data)

    return _mission_to_response(mission_data)


@router.post("/{mission_id}/fail", response_model=MissionResponse)
async def fail_mission(
    mission_id: str,
    error: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Fail mission execution

    Marks a mission as failed with error details.
    Users can only fail missions in their own tenant.
    """
    mission_data = db.query(Mission).filter(Mission.id == mission_id).first()

    if not mission_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found",
        )

    if mission_data.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant",
        )

    now = datetime.utcnow()
    mission_data.status = MissionStatus.FAILED.value
    mission_data.completed_at = now
    mission_data.error = error

    if mission_data.started_at:
        mission_data.execution_time = (now - mission_data.started_at).total_seconds()

    _update_agent_stats(db, mission_data.agent_id, success=False)
    agent = db.query(Agent).filter(Agent.id == mission_data.agent_id).first()
    if agent:
        agent.status = "idle"

    db.commit()
    db.refresh(mission_data)

    return _mission_to_response(mission_data)


@router.post("/{mission_id}/cancel", response_model=MissionResponse)
async def cancel_mission(
    mission_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Cancel mission execution

    Cancels a pending or running mission.
    """
    mission_data = db.query(Mission).filter(Mission.id == mission_id).first()

    if not mission_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission {mission_id} not found",
        )

    if mission_data.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Mission belongs to different tenant",
        )

    if mission_data.status in [
        MissionStatus.COMPLETED.value,
        MissionStatus.FAILED.value,
        MissionStatus.CANCELLED.value,
    ]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel mission in {mission_data.status} status",
        )

    mission_data.status = MissionStatus.CANCELLED.value
    mission_data.completed_at = datetime.utcnow()

    agent = db.query(Agent).filter(Agent.id == mission_data.agent_id).first()
    if agent:
        agent.status = "idle"

    db.commit()
    db.refresh(mission_data)

    return _mission_to_response(mission_data)
