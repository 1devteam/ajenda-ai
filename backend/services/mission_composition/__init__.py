"""Mission Composition Engine (ADR-0008).

Language → intent → jobs → abilities → plan/graph proposal.
Does not queue work, claim leases, or invoke tools.
"""

from backend.services.mission_composition.contracts import (
    MissionCompositionRecord,
    MissionIntent,
)
from backend.services.mission_composition.service import MissionCompositionService

__all__ = [
    "MissionCompositionRecord",
    "MissionCompositionService",
    "MissionIntent",
]
