"""
Agents API Routes
Handles agent management and operations
Migrated to SQLAlchemy database persistence

Built with Pride for Obex Blackvault
"""
from fastapi import APIRouter, HTTPException, status, Query, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

from sqlalchemy.orm import Session
from backend.database import get_db
from backend.database.models import Agent
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
# API Endpoints (ALL PROTECTED WITH AUTHENTICATION)
# ============================================================================

@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    agent: AgentCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new agent
    
    Creates a new AI agent with specified configuration.
    Agent will be created under the authenticated user's tenant.
    """
    agent_id = f"agent_{uuid.uuid4().hex[:12]}"
    
    # Use authenticated user's tenant_id
    tenant_id = current_user["tenant_id"]

    agent_data = Agent(
        id=agent_id,
        name=agent.name,
        type=agent.type.value if isinstance(agent.type, AgentType) else agent.type,
        status=AgentStatus.IDLE.value,
        tenant_id=tenant_id,
        model=agent.model,
        temperature=agent.temperature,
        system_prompt=agent.system_prompt,
        capabilities=agent.capabilities,
        config=agent.config,
        created_at=datetime.utcnow(),
        credit_balance=1000.0  # Initial balance
    )

    db.add(agent_data)
    db.commit()
    db.refresh(agent_data)

    return AgentResponse(
        id=agent_data.id,
        name=agent_data.name,
        type=agent_data.type,
        status=agent_data.status,
        tenant_id=agent_data.tenant_id,
        model=agent_data.model,
        temperature=agent_data.temperature,
        system_prompt=agent_data.system_prompt,
        capabilities=agent_data.capabilities,
        config=agent_data.config,
        created_at=agent_data.created_at,
        last_active=agent_data.last_active,
        total_missions=agent_data.total_missions,
        successful_missions=agent_data.successful_missions,
        failed_missions=agent_data.failed_missions,
        credit_balance=agent_data.credit_balance
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get agent by ID
    
    Retrieves a specific agent's information.
    Users can only access agents in their own tenant.
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found"
        )
    
    # Enforce tenant isolation
    if agent.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant"
        )

    return AgentResponse(
        id=agent.id,
        name=agent.name,
        type=agent.type,
        status=agent.status,
        tenant_id=agent.tenant_id,
        model=agent.model,
        temperature=agent.temperature,
        system_prompt=agent.system_prompt,
        capabilities=agent.capabilities,
        config=agent.config,
        created_at=agent.created_at,
        last_active=agent.last_active,
        total_missions=agent.total_missions,
        successful_missions=agent.successful_missions,
        failed_missions=agent.failed_missions,
        credit_balance=agent.credit_balance
    )


@router.get("", response_model=List[AgentResponse])
async def list_agents(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    status_filter: Optional[AgentStatus] = Query(None, alias="status", description="Filter by status"),
    type_filter: Optional[AgentType] = Query(None, alias="type", description="Filter by type"),
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
    query = db.query(Agent).filter(Agent.tenant_id == user_tenant_id)

    # Apply additional filters
    if status_filter:
        status_value = status_filter.value if isinstance(status_filter, AgentStatus) else status_filter
        query = query.filter(Agent.status == status_value)

    if type_filter:
        type_value = type_filter.value if isinstance(type_filter, AgentType) else type_filter
        query = query.filter(Agent.type == type_value)

    # Apply pagination
    agents = query.offset(skip).limit(limit).all()

    return [AgentResponse(
        id=a.id,
        name=a.name,
        type=a.type,
        status=a.status,
        tenant_id=a.tenant_id,
        model=a.model,
        temperature=a.temperature,
        system_prompt=a.system_prompt,
        capabilities=a.capabilities,
        config=a.config,
        created_at=a.created_at,
        last_active=a.last_active,
        total_missions=a.total_missions,
        successful_missions=a.successful_missions,
        failed_missions=a.failed_missions,
        credit_balance=a.credit_balance
    ) for a in agents]


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    agent: AgentUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update agent
    
    Updates an agent's configuration.
    Users can only update agents in their own tenant.
    """
    agent_data = db.query(Agent).filter(Agent.id == agent_id).first()
    
    if not agent_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found"
        )

    # Enforce tenant isolation
    if agent_data.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant"
        )

    # Update fields if provided
    if agent.name is not None:
        agent_data.name = agent.name
    if agent.status is not None:
        agent_data.status = agent.status.value if isinstance(agent.status, AgentStatus) else agent.status
    if agent.model is not None:
        agent_data.model = agent.model
    if agent.temperature is not None:
        agent_data.temperature = agent.temperature
    if agent.system_prompt is not None:
        agent_data.system_prompt = agent.system_prompt
    if agent.capabilities is not None:
        agent_data.capabilities = agent.capabilities
    if agent.config is not None:
        agent_data.config = agent.config

    agent_data.last_active = datetime.utcnow()
    
    db.commit()
    db.refresh(agent_data)

    return AgentResponse(
        id=agent_data.id,
        name=agent_data.name,
        type=agent_data.type,
        status=agent_data.status,
        tenant_id=agent_data.tenant_id,
        model=agent_data.model,
        temperature=agent_data.temperature,
        system_prompt=agent_data.system_prompt,
        capabilities=agent_data.capabilities,
        config=agent_data.config,
        created_at=agent_data.created_at,
        last_active=agent_data.last_active,
        total_missions=agent_data.total_missions,
        successful_missions=agent_data.successful_missions,
        failed_missions=agent_data.failed_missions,
        credit_balance=agent_data.credit_balance
    )


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete agent
    
    Deletes an agent from the system.
    Users can only delete agents in their own tenant.
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found"
        )
    
    # Enforce tenant isolation
    if agent.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant"
        )

    db.delete(agent)
    db.commit()
    return None


@router.post("/{agent_id}/activate", response_model=AgentResponse)
async def activate_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Activate agent
    
    Sets agent status to IDLE (ready to accept missions).
    Users can only activate agents in their own tenant.
    """
    agent_data = db.query(Agent).filter(Agent.id == agent_id).first()
    
    if not agent_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found"
        )

    # Enforce tenant isolation
    if agent_data.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant"
        )
    
    agent_data.status = AgentStatus.IDLE.value
    agent_data.last_active = datetime.utcnow()
    
    db.commit()
    db.refresh(agent_data)

    return AgentResponse(
        id=agent_data.id,
        name=agent_data.name,
        type=agent_data.type,
        status=agent_data.status,
        tenant_id=agent_data.tenant_id,
        model=agent_data.model,
        temperature=agent_data.temperature,
        system_prompt=agent_data.system_prompt,
        capabilities=agent_data.capabilities,
        config=agent_data.config,
        created_at=agent_data.created_at,
        last_active=agent_data.last_active,
        total_missions=agent_data.total_missions,
        successful_missions=agent_data.successful_missions,
        failed_missions=agent_data.failed_missions,
        credit_balance=agent_data.credit_balance
    )


@router.post("/{agent_id}/deactivate", response_model=AgentResponse)
async def deactivate_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Deactivate agent
    
    Sets agent status to OFFLINE (not accepting missions).
    Users can only deactivate agents in their own tenant.
    """
    agent_data = db.query(Agent).filter(Agent.id == agent_id).first()
    
    if not agent_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found"
        )

    # Enforce tenant isolation
    if agent_data.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant"
        )
    
    agent_data.status = AgentStatus.OFFLINE.value
    agent_data.last_active = datetime.utcnow()
    
    db.commit()
    db.refresh(agent_data)

    return AgentResponse(
        id=agent_data.id,
        name=agent_data.name,
        type=agent_data.type,
        status=agent_data.status,
        tenant_id=agent_data.tenant_id,
        model=agent_data.model,
        temperature=agent_data.temperature,
        system_prompt=agent_data.system_prompt,
        capabilities=agent_data.capabilities,
        config=agent_data.config,
        created_at=agent_data.created_at,
        last_active=agent_data.last_active,
        total_missions=agent_data.total_missions,
        successful_missions=agent_data.successful_missions,
        failed_missions=agent_data.failed_missions,
        credit_balance=agent_data.credit_balance
    )
