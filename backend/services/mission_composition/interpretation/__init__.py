"""Optional linguistic helpers for mission interpretation.

Deterministic regex core remains authoritative. Modules here only generate
normalization / fuzzy *candidates*. Missing optional libraries never crash
compose and never select abilities.
"""

from backend.services.mission_composition.interpretation.fuzzy import fuzzy_outcome_candidates
from backend.services.mission_composition.interpretation.normalize import (
    NormalizationResult,
    normalize_instruction_text,
)

__all__ = [
    "NormalizationResult",
    "fuzzy_outcome_candidates",
    "normalize_instruction_text",
]
