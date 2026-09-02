"""Mission Composition Engine (ADR-0008).

Language → intent → jobs → abilities → plan/graph proposal.
Does not queue work, claim leases, or invoke tools.
"""

from backend.services.mission_composition.contracts import (
    MissionCompositionRecord,
    MissionIntent,
)
from backend.services.mission_composition.service import MissionCompositionService
from backend.services.mission_composition.vertical_know_how import REVOPS_V1_KNOW_HOW, REVOPS_V2_KNOW_HOW

__all__ = [
    "REVOPS_V1_KNOW_HOW",
    "REVOPS_V2_KNOW_HOW",
    "MissionCompositionRecord",
    "MissionCompositionService",
    "MissionIntent",
]
