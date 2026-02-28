"""
Agents API Routes
Handles agent management and operations
Migrated to SQLAlchemy database persistence

Built with Pride for Obex Blackvault
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from sqlalchemy.orm import Session

from backend.api.routes.auth import get_current_user
from backend.database import get_db
from backend.database.models import Agent
from backend.models.domain.agent import AgentStatus, AgentType

logger = logging.getLogger(__name__)

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
    db: Session = Depends(get_db),
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
        credit_balance=1000.0,  # Initial balance
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
        credit_balance=agent_data.credit_balance,
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get agent by ID

    Retrieves a specific agent's information.
    Users can only access agents in their own tenant.
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found"
        )

    # Enforce tenant isolation
    if agent.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant",
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
        credit_balance=agent.credit_balance,
    )


@router.get("", response_model=List[AgentResponse])
async def list_agents(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    status_filter: Optional[AgentStatus] = Query(
        None, alias="status", description="Filter by status"
    ),
    type_filter: Optional[AgentType] = Query(None, alias="type", description="Filter by type"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max number of records to return"),
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
        status_value = (
            status_filter.value if isinstance(status_filter, AgentStatus) else status_filter
        )
        query = query.filter(Agent.status == status_value)

    if type_filter:
        type_value = type_filter.value if isinstance(type_filter, AgentType) else type_filter
        query = query.filter(Agent.type == type_value)

    # Apply pagination
    agents = query.offset(skip).limit(limit).all()

    return [
        AgentResponse(
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
            credit_balance=a.credit_balance,
        )
        for a in agents
    ]


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    agent: AgentUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update agent

    Updates an agent's configuration.
    Users can only update agents in their own tenant.
    """
    agent_data = db.query(Agent).filter(Agent.id == agent_id).first()

    if not agent_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found"
        )

    # Enforce tenant isolation
    if agent_data.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant",
        )

    # Update fields if provided
    if agent.name is not None:
        agent_data.name = agent.name
    if agent.status is not None:
        new_status = agent.status.value if isinstance(agent.status, AgentStatus) else agent.status
        agent_data.status = new_status
        # Record in Prometheus
        from backend.integrations.observability.prometheus_metrics import get_metrics

        get_metrics().record_agent_status(agent_data.type, new_status)
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
        credit_balance=agent_data.credit_balance,
    )


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete agent

    Deletes an agent from the system.
    Users can only delete agents in their own tenant.
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found"
        )

    # Enforce tenant isolation
    if agent.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant",
        )

    db.delete(agent)
    db.commit()
    return None


@router.post("/{agent_id}/activate", response_model=AgentResponse)
async def activate_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Activate agent

    Sets agent status to IDLE (ready to accept missions).
    Users can only activate agents in their own tenant.
    """
    agent_data = db.query(Agent).filter(Agent.id == agent_id).first()

    if not agent_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found"
        )

    # Enforce tenant isolation
    if agent_data.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant",
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
        credit_balance=agent_data.credit_balance,
    )


@router.post("/{agent_id}/deactivate", response_model=AgentResponse)
async def deactivate_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Deactivate agent

    Sets agent status to OFFLINE (not accepting missions).
    Users can only deactivate agents in their own tenant.
    """
    agent_data = db.query(Agent).filter(Agent.id == agent_id).first()

    if not agent_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found"
        )

    # Enforce tenant isolation
    if agent_data.tenant_id != current_user["tenant_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Agent belongs to different tenant",
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
        credit_balance=agent_data.credit_balance,
    )


# ============================================================================
# Specialized Agents API (NEW)
# ============================================================================


class SpecializedAgentExecuteRequest(BaseModel):
    """Request schema for executing a specialized agent"""

    agent_type: str = Field(..., description="Agent type: researcher, analyst, or developer")
    task: Dict[str, Any] = Field(..., description="Task parameters specific to agent type")

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "agent_type": "researcher",
                    "task": {
                        "query": "What is LangGraph and how does it work?",
                        "depth": "standard",
                    },
                },
                {
                    "agent_type": "analyst",
                    "task": {
                        "data": {"sales": [100, 200, 150, 300]},
                        "analysis_type": "descriptive",
                    },
                },
                {
                    "agent_type": "developer",
                    "task": {
                        "task_type": "generate",
                        "specification": "Create a function to calculate fibonacci numbers",
                    },
                },
            ]
        }


class SpecializedAgentExecuteResponse(BaseModel):
    """Response schema for specialized agent execution"""

    success: bool
    agent_type: str
    agent_id: str
    output: Dict[str, Any]
    execution_time_ms: float
    cost: float


@router.get("/types", response_model=Dict[str, Any])
async def list_specialized_agent_types(current_user: dict = Depends(get_current_user)):
    """
    List available specialized agent types

    Returns information about all specialized agent types including their
    capabilities, tools, and use cases.

    This endpoint does not require any parameters and is available to all
    authenticated users.
    """
    from backend.agents.factory.agent_factory import AgentFactory
    from backend.integrations.llm.llm_service import LLMService
    from backend.config.settings import settings

    # Create temporary factory to get agent metadata
    llm_service = LLMService(settings)
    factory = AgentFactory(llm_service)

    return factory.list_agent_types()


@router.post("/execute", response_model=SpecializedAgentExecuteResponse)
async def execute_specialized_agent(
    request: SpecializedAgentExecuteRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Execute a task with a specialized agent

    This endpoint allows direct execution of specialized agents (Researcher, Analyst, Developer)
    with their reasoning workflows and tool-calling capabilities.

    The agent will use LangGraph-based reasoning to plan, execute, reflect, and adapt
    its approach to complete the task.

    **Agent Types:**
    - `researcher`: Conducts research, gathers information, synthesizes findings
    - `analyst`: Analyzes data, performs calculations, generates insights
    - `developer`: Generates code, debugs issues, writes tests

    **Example Tasks:**
    - Researcher: `{"query": "What is quantum computing?", "depth": "standard"}`
    - Analyst: `{"data": {...}, "analysis_type": "descriptive"}`
    - Developer: `{"task_type": "generate", "specification": "Create a sorting function"}`
    """
    import time
    from backend.agents.factory.agent_factory import AgentFactory
    from backend.integrations.llm.llm_service import LLMService
    from backend.config.settings import settings

    start_time = time.time()

    try:
        # Create LLM service and agent factory
        llm_service = LLMService(settings)
        factory = AgentFactory(llm_service)

        # Validate agent type
        if request.agent_type.lower() not in ["researcher", "analyst", "developer"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid agent type: {request.agent_type}. Must be: researcher, analyst, or developer",  # noqa: E501
            )

        # Create specialized agent
        agent_id = f"direct_{request.agent_type}_{uuid.uuid4().hex[:8]}"
        agent = factory.create_specialized_agent(
            agent_type=request.agent_type,
            agent_id=agent_id,
            tenant_id=current_user["tenant_id"],
        )

        # Execute the task
        result = await agent.execute(request.task)

        # Calculate execution time
        execution_time_ms = (time.time() - start_time) * 1000

        # Calculate cost (simple model for now)
        cost = 2.0  # Base cost for specialized agent execution

        return SpecializedAgentExecuteResponse(
            success=result.get("success", False),
            agent_type=request.agent_type,
            agent_id=agent_id,
            output=result,
            execution_time_ms=execution_time_ms,
            cost=cost,
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Specialized agent execution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent execution failed: {str(e)}",
        )


@router.get("/tools", response_model=Dict[str, Any])
async def list_available_tools(current_user: dict = Depends(get_current_user)):
    """
    List all available tools for agents

    Returns information about all tools that specialized agents can use,
    including their descriptions, categories, and usage examples.
    """
    from backend.agents.tools.tool_registry import get_tool_registry, ToolCategory

    registry = get_tool_registry()
    tools = registry.get_all_tools()

    tools_info = []
    for tool in tools:
        tools_info.append(
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category.value,
                "usage": f"Used by agents for {tool.category.value} tasks",
            }
        )

    # Group by category
    by_category = {}
    for tool_info in tools_info:
        category = tool_info["category"]
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(tool_info)

    return {
        "total_tools": len(tools_info),
        "tools": tools_info,
        "by_category": by_category,
        "categories": [cat.value for cat in ToolCategory],
    }


@router.post("/research", response_model=SpecializedAgentExecuteResponse)
async def execute_researcher_agent(
    query: str = Query(..., description="Research query"),
    depth: str = Query(default="standard", description="Research depth: standard or deep"),
    current_user: dict = Depends(get_current_user),
):
    """
    Execute a research task with the Researcher agent

    Convenience endpoint for directly executing research tasks without
    needing to construct the full request payload.

    The Researcher agent will:
    1. Search the web for relevant information
    2. Synthesize findings from multiple sources
    3. Provide citations and sources
    4. Generate a comprehensive research report

    **Parameters:**
    - `query`: The research question or topic
    - `depth`: Research depth - "standard" for quick research, "deep" for comprehensive

    **Example:**
    ```
    POST /api/v1/agents/research
    {
        "query": "What is the latest research on quantum computing?",
        "depth": "deep"
    }
    ```
    """
    request = SpecializedAgentExecuteRequest(
        agent_type="researcher", task={"query": query, "depth": depth}
    )
    return await execute_specialized_agent(request, current_user)


@router.post("/analyze", response_model=SpecializedAgentExecuteResponse)
async def execute_analyst_agent(
    data: Dict[str, Any] = Body(..., description="Data to analyze"),
    analysis_type: str = Body(default="descriptive", description="Type of analysis"),
    current_user: dict = Depends(get_current_user),
):
    """
    Execute an analysis task with the Analyst agent

    Convenience endpoint for directly executing data analysis tasks.

    The Analyst agent will:
    1. Analyze the provided data
    2. Perform statistical calculations
    3. Identify patterns and trends
    4. Generate actionable insights

    **Parameters:**
    - `data`: The data to analyze (dict, list, or structured data)
    - `analysis_type`: Type of analysis - "descriptive", "comparative", "predictive"

    **Example:**
    ```
    POST /api/v1/agents/analyze
    {
        "data": {"sales": [100, 200, 150, 300], "costs": [50, 80, 60, 120]},
        "analysis_type": "descriptive"
    }
    ```
    """
    request = SpecializedAgentExecuteRequest(
        agent_type="analyst", task={"data": data, "analysis_type": analysis_type}
    )
    return await execute_specialized_agent(request, current_user)


@router.post("/develop", response_model=SpecializedAgentExecuteResponse)
async def execute_developer_agent(
    specification: str = Body(..., description="Code specification or task description"),
    task_type: str = Body(
        default="generate", description="Task type: generate, debug, review, test"
    ),
    current_user: dict = Depends(get_current_user),
):
    """
    Execute a development task with the Developer agent

    Convenience endpoint for directly executing code-related tasks.

    The Developer agent will:
    1. Generate code based on specifications
    2. Debug and fix code issues
    3. Write unit tests
    4. Review code and provide feedback

    **Parameters:**
    - `specification`: Description of what code to generate or task to perform
    - `task_type`: Type of task - "generate", "debug", "review", "test"

    **Example:**
    ```
    POST /api/v1/agents/develop
    {
        "specification": "Create a function to calculate the fibonacci sequence",
        "task_type": "generate"
    }
    ```
    """
    request = SpecializedAgentExecuteRequest(
        agent_type="developer",
        task={"specification": specification, "task_type": task_type},
    )
    return await execute_specialized_agent(request, current_user)
