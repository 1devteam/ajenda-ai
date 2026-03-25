"""
Workforce Fleet Domain Models

Defines the first-class fleet abstraction that sits between mission execution
and individual agents.

Incremental refactor rule:
- introduce fleet as a domain concept first
- do not break existing mission -> agent execution yet
- do not modify AgentFactory in this step
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WorkforceFleetStatus(str, Enum):
    """Lifecycle state of a workforce fleet."""

    PENDING = "pending"
    PROVISIONING = "provisioning"
    READY = "ready"
    ACTIVE = "active"
    DEGRADED = "degraded"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


class WorkforceFleetType(str, Enum):
    """How the fleet is intended to operate."""

    SINGLE = "single"
    SPECIALIZED = "specialized"
    SWARM = "swarm"
    BRANCHED = "branched"


class WorkforceFleet(BaseModel):
    """
    First-class workforce fleet model.

    A fleet is the governed execution container that owns one or more agents
    for a mission or branch of work.

    This model is intentionally additive in the first refactor step:
    existing mission execution may continue using a single primary agent while
    we begin recording fleet identity explicitly.
    """

    id: str
    mission_id: str
    tenant_id: str

    status: WorkforceFleetStatus = WorkforceFleetStatus.PENDING
    fleet_type: WorkforceFleetType = WorkforceFleetType.SINGLE

    objective: str
    primary_agent_id: Optional[str] = None
    agent_ids: List[str] = Field(default_factory=list)

    branch_id: Optional[str] = None
    parent_fleet_id: Optional[str] = None

    metadata: Dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    activated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    class Config:
        use_enum_values = True
