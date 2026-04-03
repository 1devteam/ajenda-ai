"""Foundation health checker — continuity floor assessment for RuntimeGovernor.

Previously named ControlSpecialist (misleading — sounds like a user-facing
service). Renamed to FoundationHealthChecker for clarity. The old name is
kept as a deprecated alias to avoid breaking any external tooling.

This is an internal service used exclusively by RuntimeGovernor.
It is NOT exposed as a public API dependency.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ContinuityAssessment:
    """Result of a foundation health check."""
    dependency_healthy: bool
    continuity_floor_met: bool
    signal: str
    failure_reason: str = ""


class FoundationHealthChecker:
    """Internal health-check delegate for RuntimeGovernor.

    Checks whether the database (and in future: Redis, queue) are reachable
    and returns a ContinuityAssessment that RuntimeGovernor uses to determine
    the current RuntimeMode.

    This class is NOT a public API dependency. It must not be injected into
    route handlers. Use RuntimeGovernor.evaluate() at the service layer.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def assess_foundation_health(self) -> ContinuityAssessment:
        """Check database connectivity and return a ContinuityAssessment."""
        db_alive = self._database_alive()
        if db_alive:
            return ContinuityAssessment(
                dependency_healthy=True,
                continuity_floor_met=True,
                signal="normal",
                failure_reason="",
            )
        return ContinuityAssessment(
            dependency_healthy=False,
            continuity_floor_met=False,
            signal="degraded",
            failure_reason="Database connectivity check failed (SELECT 1 raised exception)",
        )

    def _database_alive(self) -> bool:
        try:
            self._session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False


# Deprecated alias — kept for backward compatibility with any tooling
# that references ControlSpecialist by name. Remove in v2.0.
ControlSpecialist = FoundationHealthChecker
