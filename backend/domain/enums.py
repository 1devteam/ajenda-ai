"""Domain state enumerations for the Ajenda AI governed runtime.

All state values are stored as lowercase strings in the database.
The check constraints in migrations enforce the allowed values.
State transitions are enforced by backend/runtime/state_machine.py.
"""
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


class ExecutionTaskState(StrEnum):
    PLANNED = "planned"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    RECOVERING = "recovering"   # Lease expired; task being re-enqueued by RuntimeMaintainer
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"


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


class ExecutionBranchState(StrEnum):
    OPEN = "open"
    RUNNING = "running"
    SELECTED = "selected"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    CLOSED = "closed"


class WorkerLeaseState(StrEnum):
    CLAIMED = "claimed"
    ACTIVE = "active"
    EXPIRED = "expired"
    RELEASED = "released"
