"""Centralized state transition validator for the Ajenda AI governed runtime.

All state transitions for all domain entities are defined here.
This is the single source of truth for what transitions are legal.

Attempting an illegal transition raises InvalidTransitionError, which
the service layer must handle (typically by returning a 409 Conflict).

Task state machine (with 'recovering' state added in migration 0004,
'pending_review' added in migration 0008):

    planned → queued | pending_review
    queued → claimed | cancelled
    claimed → queued | running | cancelled
    running → blocked | completed | failed | recovering
    recovering → queued | dead_lettered
    blocked → queued
    failed → queued | dead_lettered
    pending_review → queued | cancelled

The 'recovering' state is entered when a worker's lease expires while the
task is in 'running' state. RuntimeMaintainer transitions running→recovering,
then recovering→queued to re-enqueue for pickup by a healthy worker.

The 'pending_review' state is entered by PolicyGuardian when a task requires
human review before execution (e.g. employment decisions, financial decisions
in regulated jurisdictions). A human reviewer approves (→queued) or rejects
(→cancelled) the task via the admin API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


class InvalidTransitionError(ValueError):
    """Raised when a forbidden state transition is attempted."""


@dataclass(frozen=True, slots=True)
class TransitionRule:
    source: str
    target: str


class StateMachine:
    """Centralized state transition validator for all domain entities."""

    _MISSION_ALLOWED: ClassVar[dict[str, set[str]]] = {
        "planned": {"approved"},
        "approved": {"queued"},
        "queued": {"running", "cancelled"},
        "running": {"paused", "completed", "failed", "cancelled"},
        "paused": {"running"},
        "completed": {"archived"},
        "failed": {"archived"},
        "cancelled": {"archived"},
    }

    _FLEET_ALLOWED: ClassVar[dict[str, set[str]]] = {
        "planned": {"provisioning"},
        "provisioning": {"ready"},
        "ready": {"running"},
        "running": {"paused", "completed", "failed"},
        "paused": {"running"},
        "completed": {"retired"},
        "failed": {"retired"},
    }

    _AGENT_ALLOWED: ClassVar[dict[str, set[str]]] = {
        "planned": {"provisioned"},
        "provisioned": {"assigned"},
        "assigned": {"running"},
        "running": {"paused", "completed", "failed"},
        "paused": {"running"},
        "completed": {"retired"},
        "failed": {"retired"},
    }

    _TASK_ALLOWED: ClassVar[dict[str, set[str]]] = {
        "planned": {"queued", "pending_review"},
        "queued": {"claimed", "cancelled"},
        "claimed": {"queued", "running", "cancelled"},
        "running": {"blocked", "completed", "failed", "recovering"},
        # recovering: transient state entered when a worker crashes mid-execution.
        # The runtime_maintainer transitions stale running tasks into recovering
        # before re-queuing them for retry or dead-lettering on max retries.
        "recovering": {"queued", "dead_lettered"},
        "blocked": {"queued"},
        "failed": {"queued", "dead_lettered"},
        # pending_review: entered by PolicyGuardian when a task requires human
        # approval before execution (e.g. employment/financial decisions in
        # regulated jurisdictions). Approved → queued; rejected → cancelled.
        "pending_review": {"queued", "cancelled"},
    }

    _BRANCH_ALLOWED: ClassVar[dict[str, set[str]]] = {
        "open": {"running"},
        "running": {"selected", "superseded", "failed"},
        "selected": {"closed"},
        "superseded": {"closed"},
        "failed": {"closed"},
    }

    _LEASE_ALLOWED: ClassVar[dict[str, set[str]]] = {
        "claimed": {"active"},
        "active": {"released", "expired"},
        "expired": {"released"},
    }

    @classmethod
    def ensure_mission_transition(cls, source: str, target: str) -> None:
        cls._ensure(cls._MISSION_ALLOWED, source, target, "mission")

    @classmethod
    def ensure_fleet_transition(cls, source: str, target: str) -> None:
        cls._ensure(cls._FLEET_ALLOWED, source, target, "fleet")

    @classmethod
    def ensure_agent_transition(cls, source: str, target: str) -> None:
        cls._ensure(cls._AGENT_ALLOWED, source, target, "agent")

    @classmethod
    def ensure_task_transition(cls, source: str, target: str) -> None:
        cls._ensure(cls._TASK_ALLOWED, source, target, "task")

    @classmethod
    def ensure_branch_transition(cls, source: str, target: str) -> None:
        cls._ensure(cls._BRANCH_ALLOWED, source, target, "branch")

    @classmethod
    def ensure_lease_transition(cls, source: str, target: str) -> None:
        cls._ensure(cls._LEASE_ALLOWED, source, target, "lease")

    @staticmethod
    def _ensure(
        allowed: dict[str, set[str]],
        source: str,
        target: str,
        kind: str,
    ) -> None:
        if target not in allowed.get(source, set()):
            raise InvalidTransitionError(
                f"Invalid {kind} transition: {source!r} -> {target!r}. "
                f"Allowed from {source!r}: {sorted(allowed.get(source, set()))}"
            )
