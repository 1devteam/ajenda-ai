from __future__ import annotations

from dataclasses import dataclass


class InvalidTransitionError(ValueError):
    """Raised when a forbidden state transition is attempted."""


@dataclass(frozen=True, slots=True)
class TransitionRule:
    source: str
    target: str


class StateMachine:
    """Centralized Phase 2 state transition validator."""

    _MISSION_ALLOWED: dict[str, set[str]] = {
        "planned": {"approved"},
        "approved": {"queued"},
        "queued": {"running", "cancelled"},
        "running": {"paused", "completed", "failed", "cancelled"},
        "paused": {"running"},
        "completed": {"archived"},
        "failed": {"archived"},
        "cancelled": {"archived"},
    }

    _FLEET_ALLOWED: dict[str, set[str]] = {
        "planned": {"provisioning"},
        "provisioning": {"ready"},
        "ready": {"running"},
        "running": {"paused", "completed", "failed"},
        "paused": {"running"},
        "completed": {"retired"},
        "failed": {"retired"},
    }

    _AGENT_ALLOWED: dict[str, set[str]] = {
        "planned": {"provisioned"},
        "provisioned": {"assigned"},
        "assigned": {"running"},
        "running": {"paused", "completed", "failed"},
        "paused": {"running"},
        "completed": {"retired"},
        "failed": {"retired"},
    }

    _TASK_ALLOWED: dict[str, set[str]] = {
        "planned": {"queued"},
        "queued": {"claimed", "cancelled"},
        "claimed": {"running", "cancelled"},
        "running": {"blocked", "completed", "failed"},
        "blocked": {"queued"},
        "failed": {"queued", "dead_lettered"},
    }

    _BRANCH_ALLOWED: dict[str, set[str]] = {
        "open": {"running"},
        "running": {"selected", "superseded", "failed"},
        "selected": {"closed"},
        "superseded": {"closed"},
        "failed": {"closed"},
    }

    _LEASE_ALLOWED: dict[str, set[str]] = {
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
    def _ensure(allowed: dict[str, set[str]], source: str, target: str, kind: str) -> None:
        if target not in allowed.get(source, set()):
            raise InvalidTransitionError(f"invalid {kind} transition: {source} -> {target}")
