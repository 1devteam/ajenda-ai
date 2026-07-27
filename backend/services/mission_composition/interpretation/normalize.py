"""Instruction normalization: whitespace, protected tokens, optional spelling."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.services.mission_composition.interpretation.spelling import (
    SpellingCorrection,
    apply_spelling_candidates,
)

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_WS_RE = re.compile(r"\s+")


@dataclass(slots=True)
class NormalizationResult:
    original: str
    normalized: str
    spelling_corrections: list[SpellingCorrection] = field(default_factory=list)
    components_active: list[str] = field(default_factory=list)


def normalize_instruction_text(
    instruction: str,
    *,
    spelling_enabled: bool = True,
) -> NormalizationResult:
    """Preserve meaning while applying safe whitespace + optional spelling fixes.

    URLs and emails are protected (not spelling-corrected). Original instruction
    is always retained by the caller for audit.
    """

    original = instruction
    text = instruction.strip()
    text = _WS_RE.sub(" ", text)

    components: list[str] = ["regex_core", "normalize_whitespace"]
    protected: list[tuple[str, str]] = []

    def _protect(match: re.Match[str]) -> str:
        token = f"__PROT_{len(protected)}__"
        protected.append((token, match.group(0)))
        return token

    text = _URL_RE.sub(_protect, text)
    text = _EMAIL_RE.sub(_protect, text)

    corrections: list[SpellingCorrection] = []
    if spelling_enabled:
        text, corrections, spell_components = apply_spelling_candidates(text)
        components.extend(spell_components)

    for token, value in protected:
        text = text.replace(token, value)

    return NormalizationResult(
        original=original,
        normalized=text,
        spelling_corrections=corrections,
        components_active=components,
    )
