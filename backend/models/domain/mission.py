"""
Mission Domain Models
Defines mission states and data structures
"""
from enum import Enum
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class MissionStatus(Enum):
    """Mission execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class MissionPriority(Enum):
    """Mission priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class Mission(BaseModel):
    """Mission domain model"""
    id: str
    objective: str
    status: MissionStatus = MissionStatus.PENDING
    priority: MissionPriority = MissionPriority.NORMAL
    agent_id: str
    tenant_id: str
    created_at: datetime = datetime.utcnow()
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    steps: List[Dict[str, Any]] = []
    context: Dict[str, Any] = {}
    
    class Config:
        use_enum_values = True


class MissionResult(BaseModel):
    """Result of a mission execution"""
    mission_id: str
    status: MissionStatus
    output: Optional[Any] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    tokens_used: int = 0
    cost: float = 0.0
    
    class Config:
        use_enum_values = True
