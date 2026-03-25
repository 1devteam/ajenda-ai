"""
Execution Task Domain Model

Introduces a first-class governed unit of execution work.

Incremental refactor rules:
- additive only
- does not replace SubMission yet
- does not require scheduler / saga changes yet
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExecutionTaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionTaskType(str, Enum):
    RESEARCH = "research"
    ANALYSIS = "analysis"
    GENERATION = "generation"
    COORDINATION = "coordination"
    GENERIC = "generic"


class ExecutionTask(BaseModel):
    """
    First-class governed execution task.

    Transitional intent:
    - can coexist with legacy SubMission concepts
    - can be attached to a mission and optionally to a fleet
    - gives us a stable object for future branching and retries
    """

    id: str
    mission_id: str
    tenant_id: str

    title: str
    objective: str

    status: ExecutionTaskStatus = ExecutionTaskStatus.PENDING
    task_type: ExecutionTaskType = ExecutionTaskType.GENERIC

    fleet_id: Optional[str] = None
    assigned_agent_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    branch_id: Optional[str] = None

    input_payload: Dict[str, Any] = Field(default_factory=dict)
    output_payload: Dict[str, Any] = Field(default_factory=dict)
    dependencies: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    class Config:
        use_enum_values = True
