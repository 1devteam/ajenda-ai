"""
Agents API Routes
Handles agent management and operations

Built with Pride for Obex Blackvault
"""
from fastapi import APIRouter, HTTPException, status, Query, Depends
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

from backend.models.domain.agent import AgentStatus, AgentType

# Import authentication dependency
from backend.api.routes.auth import get_current_user

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


# ============================================================================
# Request/Response Models
# ============================================================================

class AgentCreate(BaseModel):
    """Schema for creating a new agent"""
    name: str = Field(..., min_length=1, max_length=100, description="Agent name")
    type: AgentType = Field(default=AgentType.CUSTOM, description="Agent type")
    model: str = Field(default="gpt-4", description="LLM model")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Temperature")
    system_prompt: Optional[str] = Field(None, description="System prompt")
    capabilities: List[str] = Field(default_factory=list, description="Agent capabilities")
    config: Dict[str, Any] = Field(default_factory=dict, description="Additional configuration")


class AgentUpdate(BaseModel):
    """Schema for updating an agent"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    status: Optional[AgentStatus] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    system_prompt: Optional[str] = None
    capabilities: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None


class AgentResponse(BaseModel):
    """Agent response model"""
    id: str
    name: str
    type: str
    status: str
    tenant_id: str
    model: str
    temperature: float
    system_prompt: Optional[str] = None
    capabilities: List[str]
    config: Dict[str, Any]
    created_at: datetime
    last_active: Optional[datetime] = None
    total_missions: int = 0
    successful_missions: int = 0
    failed_missions: int = 0
    credit_balance: float = 0.0


# ============================================================================
# In-Memory Storage (Replace with database in production)
# ============================================================================

_agents_db: dict[str, dict] = {}


# ============================================================================
# API Endpoints (ALL PROTECTED WITH AUTHENTICATION)
# ============================================================================

@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    agent: AgentCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new agent
    
    Creates a new AI agent with specified configuration.
    Agent will be created under the authenticated user's tenant.
    """
    agent_id = f"agent_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow()
    
    # Use authenticated user's tenant_id
    tenant_id = current_user["tenant_id"]

    agent_data = {
        "id": agent_id,
        "name": agent.name,
        "type": agent.type.value if isinstance(agent.type, AgentType) else agent.type,
        "status": AgentStatus.IDLE.value,
        "tenant_id": tenant_id,
        "model": agent.model,
        "temperature": agent.temperature,
        "system_prompt": agent.system_prompt,
        "capabilities": agent.capabilities,
        "config": agent.config,
        "created_at": now,
        "last_active": None,
        "total_missions": 0,
        "successful_missions": 0,
        "failed_missions": 0,
        "credit_balance": 1000.0  # Initial balance
    }

    _agents_db[agent_id] = agent_data

    return AgentResponse(**agent_data)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get agent by ID
    
    Retrieves a specific agent's information.
    Users can only access agents in their own tenant.
    """
    if agent_id not in _agents_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found"
        )
    
    agent = _agents_db[agent_id]
    
    # Enforce tenant isolation
    if agent["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant"
        )

    return AgentResponse(**agent)


@router.get("", response_model=List[AgentResponse])
async def list_agents(
    current_user: dict = Depends(get_current_user),
    status: Optional[AgentStatus] = Query(None, description="Filter by status"),
    type: Optional[AgentType] = Query(None, description="Filter by type"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max number of records to return")
):
    """
    List all agents
    
    Returns a list of agents with optional filtering.
    Users can only see agents in their own tenant.
    """
    # Filter by authenticated user's tenant only
    user_tenant_id = current_user["tenant_id"]
    agents = [a for a in _agents_db.values() if a["tenant_id"] == user_tenant_id]

    # Apply additional filters
    if status:
        status_value = status.value if isinstance(status, AgentStatus) else status
        agents = [a for a in agents if a["status"] == status_value]

    if type:
        type_value = type.value if isinstance(type, AgentType) else type
        agents = [a for a in agents if a["type"] == type_value]

    # Apply pagination
    agents = agents[skip:skip + limit]

    return [AgentResponse(**a) for a in agents]


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    agent: AgentUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Update agent
    
    Updates an agent's configuration.
    Users can only update agents in their own tenant.
    """
    if agent_id not in _agents_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found"
        )

    agent_data = _agents_db[agent_id]
    
    # Enforce tenant isolation
    if agent_data["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant"
        )

    # Update fields if provided
    if agent.name is not None:
        agent_data["name"] = agent.name
    if agent.status is not None:
        agent_data["status"] = agent.status.value if isinstance(agent.status, AgentStatus) else agent.status
    if agent.model is not None:
        agent_data["model"] = agent.model
    if agent.temperature is not None:
        agent_data["temperature"] = agent.temperature
    if agent.system_prompt is not None:
        agent_data["system_prompt"] = agent.system_prompt
    if agent.capabilities is not None:
        agent_data["capabilities"] = agent.capabilities
    if agent.config is not None:
        agent_data["config"] = agent.config

    agent_data["last_active"] = datetime.utcnow()

    return AgentResponse(**agent_data)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete agent
    
    Deletes an agent from the system.
    Users can only delete agents in their own tenant.
    """
    if agent_id not in _agents_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found"
        )
    
    agent = _agents_db[agent_id]
    
    # Enforce tenant isolation
    if agent["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant"
        )

    del _agents_db[agent_id]
    return None


@router.post("/{agent_id}/activate", response_model=AgentResponse)
async def activate_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Activate agent
    
    Sets agent status to IDLE (ready to accept missions).
    Users can only activate agents in their own tenant.
    """
    if agent_id not in _agents_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found"
        )

    agent_data = _agents_db[agent_id]
    
    # Enforce tenant isolation
    if agent_data["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant"
        )
    
    agent_data["status"] = AgentStatus.IDLE.value
    agent_data["last_active"] = datetime.utcnow()

    return AgentResponse(**agent_data)


@router.post("/{agent_id}/deactivate", response_model=AgentResponse)
async def deactivate_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Deactivate agent
    
    Sets agent status to OFFLINE (not accepting missions).
    Users can only deactivate agents in their own tenant.
    """
    if agent_id not in _agents_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found"
        )

    agent_data = _agents_db[agent_id]
    
    # Enforce tenant isolation
    if agent_data["tenant_id"] != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant"
        )
    
    agent_data["status"] = AgentStatus.OFFLINE.value
    agent_data["last_active"] = datetime.utcnow()

    return AgentResponse(**agent_data)
