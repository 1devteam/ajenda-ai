"""Runtime Governor — global gatekeeper for governed execution.

Previous defect: RuntimeDecision.execution_allowed was hardcoded to False
in ALL modes, including NORMAL. This made the control plane ceremonial —
every task was blocked regardless of system health.

This implementation:
- NORMAL: execution_allowed=True, provisioning_allowed=True
- DEGRADED: execution_allowed=True (drain in progress), provisioning_allowed=False
- RESTRICTED: execution_allowed=False (operator-imposed halt)
- RECOVERY: execution_allowed=False (active recovery in progress)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from backend.services.control_specialist import ControlSpecialist

logger = logging.getLogger("ajenda.runtime_governor")


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
    """Global runtime gatekeeper for bounded safe behavior.

    Evaluates system health and returns a RuntimeDecision that
    ExecutionCoordinator and WorkforceProvisioner must respect.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._control_specialist = ControlSpecialist(session)

    def evaluate(self) -> RuntimeDecision:
        """Evaluate current system health and return a binding runtime decision."""
        try:
            assessment = self._control_specialist.assess_foundation_health()
        except Exception as exc:
            logger.error("runtime_governor_health_check_failed", extra={"error": str(exc)})
            return RuntimeDecision(
                mode=RuntimeMode.DEGRADED,
                provisioning_allowed=False,
                execution_allowed=True,  # Drain existing work; block new provisioning
                reason=f"Health check failed — operating in degraded drain mode: {exc}",
            )

        if assessment.continuity_floor_met:
            logger.debug("runtime_governor_decision", extra={"mode": "normal"})
            return RuntimeDecision(
                mode=RuntimeMode.NORMAL,
                provisioning_allowed=True,
                execution_allowed=True,
                reason="All dependencies healthy. Normal execution permitted.",
            )

        logger.warning(
            "runtime_governor_degraded",
            extra={"reason": assessment.failure_reason if hasattr(assessment, "failure_reason") else "unknown"},
        )
        return RuntimeDecision(
            mode=RuntimeMode.DEGRADED,
            provisioning_allowed=False,
            execution_allowed=True,  # Allow existing tasks to drain
            reason="Dependency health degraded below continuity floor. New provisioning blocked.",
        )

    def force_restricted(self, reason: str) -> RuntimeDecision:
        """Operator-invoked halt. Blocks all execution immediately."""
        logger.critical("runtime_governor_restricted", extra={"reason": reason})
        return RuntimeDecision(
            mode=RuntimeMode.RESTRICTED,
            provisioning_allowed=False,
            execution_allowed=False,
            reason=reason,
        )
