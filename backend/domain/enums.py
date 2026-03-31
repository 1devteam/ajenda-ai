from __future__ import annotations

from enum import StrEnum


class MissionState(StrEnum):
    PLANNED = "planned"
    APPROVED = "approved"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class WorkforceFleetState(StrEnum):
    PLANNED = "planned"
    PROVISIONING = "provisioning"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    RETIRED = "retired"


class UserWorkforceAgentState(StrEnum):
    PLANNED = "planned"
    PROVISIONED = "provisioned"
    ASSIGNED = "assigned"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    RETIRED = "retired"


class ExecutionTaskState(StrEnum):
    PLANNED = "planned"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTERED = "dead_lettered"


class ExecutionBranchState(StrEnum):
    OPEN = "open"
    RUNNING = "running"
    SUPERSEDED = "superseded"
    SELECTED = "selected"
    CLOSED = "closed"
    FAILED = "failed"


class WorkerLeaseState(StrEnum):
    CLAIMED = "claimed"
    ACTIVE = "active"
    EXPIRED = "expired"
    RELEASED = "released"
