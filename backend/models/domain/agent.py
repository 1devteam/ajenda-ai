"""
Agent Domain Models
Defines agent states and data structures
"""

from enum import Enum
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AgentStatus(Enum):
    """Agent operational status"""

    IDLE = "idle"
    BUSY = "busy"
    THINKING = "thinking"
    EXECUTING = "executing"
    WAITING = "waiting"
    ERROR = "error"
    OFFLINE = "offline"


class AgentType(Enum):
    """Types of agents in the system"""

    COMMANDER = "commander"
    GUARDIAN = "guardian"
    ARCHIVIST = "archivist"
    FORK = "fork"
    CUSTOM = "custom"


class Agent(BaseModel):
    """Agent domain model"""

    id: str
    name: str
    type: AgentType
    status: AgentStatus = AgentStatus.IDLE
    tenant_id: str
    model: str  # LLM model (e.g., "gpt-4")
    temperature: float = 0.7
    created_at: datetime = datetime.utcnow()
    last_active: Optional[datetime] = None
    total_missions: int = 0
    successful_missions: int = 0
    failed_missions: int = 0

    class Config:
        use_enum_values = True
