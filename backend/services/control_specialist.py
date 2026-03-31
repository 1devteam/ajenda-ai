from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ContinuityAssessment:
    dependency_healthy: bool
    continuity_floor_met: bool
    signal: str


class ControlSpecialist:
    """Foundational continuity-floor logic for Phase 1."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def assess_foundation_health(self) -> ContinuityAssessment:
        dependency_healthy = self._database_alive()
        signal = "normal" if dependency_healthy else "degraded"
        return ContinuityAssessment(
            dependency_healthy=dependency_healthy,
            continuity_floor_met=dependency_healthy,
            signal=signal,
        )

    def _database_alive(self) -> bool:
        try:
            self._session.execute(text("SELECT 1"))
        except Exception:
            return False
        return True
