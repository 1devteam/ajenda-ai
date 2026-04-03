"""Domain state enumerations for the Ajenda AI governed runtime.

All state values are stored as lowercase strings in the database.
The check constraints in migrations enforce the allowed values.
State transitions are enforced by backend/runtime/state_machine.py.
"""
from __future__ import annotations
from enum import StrEnum


class ComplianceCategory(StrEnum):
    """Categorizes the compliance domain of an ExecutionTask.

    Used by PolicyGuardian to determine which regulatory rulesets apply.
    """
    OPERATIONAL = "operational"
    CONSUMER_INTERACTION = "consumer_interaction"
    MARKETING = "marketing"
    EMPLOYMENT = "employment"
    FINANCIAL = "financial"
    HEALTHCARE = "healthcare"
    PUBLIC_CONTENT = "public_content"


class ComplianceJurisdiction(StrEnum):
    """Identifies the regulatory jurisdiction governing an ExecutionTask.

    Determines which specific regulations PolicyGuardian enforces.
    """
    EU = "eu"                    # EU AI Act
    COLORADO = "colorado"        # Colorado SB24-205
    NYC = "nyc"                  # NYC Local Law 144
    FEDERAL_US = "federal_us"    # FTC Act / TCPA
    GLOBAL = "global"            # Cross-jurisdictional baseline


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
    RECOVERING = "recovering"      # Lease expired; task being re-enqueued by RuntimeMaintainer
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"
    PENDING_REVIEW = "pending_review"  # Compliance: requires human review before execution


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
