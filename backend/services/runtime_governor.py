from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from backend.services.control_specialist import ControlSpecialist


class RuntimeMode(StrEnum):
    NORMAL = "normal"
    DEGRADED = "degraded"
    RESTRICTED = "restricted"
    RECOVERY = "recovery"


@dataclass(frozen=True, slots=True)
class RuntimeDecision:
    mode: RuntimeMode
    provisioning_allowed: bool
    execution_allowed: bool
    reason: str


class RuntimeGovernor:
    """Phase 1 global runtime gatekeeper for bounded safe behavior."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._control_specialist = ControlSpecialist(session)

    def evaluate(self) -> RuntimeDecision:
        assessment = self._control_specialist.assess_foundation_health()
        if assessment.continuity_floor_met:
            return RuntimeDecision(
                mode=RuntimeMode.NORMAL,
                provisioning_allowed=False,
                execution_allowed=False,
                reason="Phase 1 foundation forbids governed runtime execution.",
            )
        return RuntimeDecision(
            mode=RuntimeMode.DEGRADED,
            provisioning_allowed=False,
            execution_allowed=False,
            reason="Dependency health degraded below continuity floor.",
        )
