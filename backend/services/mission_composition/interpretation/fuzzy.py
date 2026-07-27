"""Controlled fuzzy matching against approved outcome alias vocabulary.

RapidFuzz is optional. When unavailable, returns no fuzzy candidates.
Fuzzy matches never select abilities — interpreter may only propose outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.services.mission_composition.contracts import CANONICAL_OUTCOMES, LEGACY_OUTCOME_ALIASES, CanonicalOutcome

# High threshold: only strong phrase similarity proposes an outcome.
_HIGH_SCORE = 90.0
_MEDIUM_SCORE = 80.0


@dataclass(frozen=True, slots=True)
class FuzzyOutcomeCandidate:
    outcome: CanonicalOutcome
    score: float
    matched_alias: str
    band: str  # high | medium


def _alias_table() -> list[tuple[str, CanonicalOutcome]]:
    rows: list[tuple[str, CanonicalOutcome]] = []
    for alias, outcome in LEGACY_OUTCOME_ALIASES.items():
        rows.append((alias, outcome))
    for outcome in sorted(CANONICAL_OUTCOMES):
        rows.append((outcome.replace("_", " "), outcome))  # type: ignore[arg-type]
    return rows


def fuzzy_outcome_candidates(
    text: str,
    *,
    enabled: bool = True,
    already: set[str] | None = None,
) -> tuple[list[FuzzyOutcomeCandidate], list[str]]:
    """Return fuzzy outcome candidates and active components."""

    if not enabled:
        return [], []
    already = already or set()
    try:
        from rapidfuzz import fuzz, process  # type: ignore[import-untyped]
    except Exception:
        return [], []

    components = ["rapidfuzz"]
    aliases = _alias_table()
    choices = [alias for alias, _ in aliases]
    # Extract candidate windows: full text + simple bigrams/trigrams of words
    words = text.lower().split()
    windows = {" ".join(words)}
    for n in (2, 3, 4):
        for i in range(0, max(0, len(words) - n + 1)):
            windows.add(" ".join(words[i : i + n]))

    best: dict[str, FuzzyOutcomeCandidate] = {}
    for window in windows:
        if len(window) < 4:
            continue
        matches = process.extract(window, choices, scorer=fuzz.token_set_ratio, limit=2)
        for alias, score, _idx in matches:
            if score < _MEDIUM_SCORE:
                continue
            # map alias → outcome
            outcome: CanonicalOutcome | None = None
            for a, o in aliases:
                if a == alias:
                    outcome = o
                    break
            if outcome is None or outcome in already:
                continue
            band = "high" if score >= _HIGH_SCORE else "medium"
            prev = best.get(outcome)
            if prev is None or score > prev.score:
                best[outcome] = FuzzyOutcomeCandidate(
                    outcome=outcome,
                    score=float(score),
                    matched_alias=alias,
                    band=band,
                )

    # Only return high-confidence as proposable; medium retained for restatement hints.
    return list(best.values()), components
