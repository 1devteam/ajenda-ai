"""
Execution Branch Domain Model

Introduces a first-class governed branching object for retry, divergence,
forked exploration, and controlled alternative execution paths.

Incremental refactor rules:
- additive only
- no scheduler / saga rewrite
- no replacement of existing orchestration logic yet
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ExecutionBranchStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    MERGED = "merged"
    ABANDONED = "abandoned"
    FAILED = "failed"
    COMPLETED = "completed"


class ExecutionBranchType(str, Enum):
    RETRY = "retry"
    FORK = "fork"
    DIVERGENCE = "divergence"
    ESCALATION = "escalation"
    RECOVERY = "recovery"


class ExecutionBranch(BaseModel):
    """
    First-class governed branch of execution.

    A branch represents a controlled divergence from a mission, task,
    or fleet execution path.
    """

    id: str
    mission_id: str
    tenant_id: str

    branch_type: ExecutionBranchType
    status: ExecutionBranchStatus = ExecutionBranchStatus.PENDING

    objective: str
    source_task_id: Optional[str] = None
    source_fleet_id: Optional[str] = None
    parent_branch_id: Optional[str] = None

    spawned_fleet_id: Optional[str] = None
    spawned_task_id: Optional[str] = None

    reason: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    activated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    class Config:
        use_enum_values = True
