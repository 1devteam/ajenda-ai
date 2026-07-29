"""Interpreter-owned ability / outcome vocabulary.

Natural-language aliases live here — not in ability manifests, job catalogs, or
connector OAuth config. Aliases only propose canonical outcomes; they never
select runtime actions or grant authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.services.mission_composition.contracts import CanonicalOutcome

# Extra phrase aliases merged into LEGACY_OUTCOME_ALIASES consumers via lookup.
ABILITY_OUTCOME_ALIASES: dict[str, CanonicalOutcome] = {
    # Qualify / score / rank family
    "score them": "qualify_prospects",
    "score it": "qualify_prospects",
    "score these": "qualify_prospects",
    "score those": "qualify_prospects",
    "score the prospects": "qualify_prospects",
    "score the leads": "qualify_prospects",
    "score competitors": "qualify_prospects",
    "score the competitors": "qualify_prospects",
    "rank them": "qualify_prospects",
    "rank the prospects": "qualify_prospects",
    "rank the leads": "qualify_prospects",
    "rate them": "qualify_prospects",
    "grade them": "qualify_prospects",
    "pick the strongest": "qualify_prospects",
    "pick the best": "qualify_prospects",
    "top prospects": "qualify_prospects",
    "strongest prospects": "qualify_prospects",
    "best prospects": "qualify_prospects",
    "identify the strongest": "qualify_prospects",
    "identify the best": "qualify_prospects",
    # Research
    "find competitors": "research_prospects",
    "research competitors": "research_prospects",
    "competitor research": "research_prospects",
    # Outreach
    "prepare outreach drafts": "prepare_outreach",
    "draft outreach": "prepare_outreach",
    "write introductions": "prepare_outreach",
    # Calendar read
    "check my calendar": "read_calendar",
    "calendar for": "read_calendar",
}

# Regex patterns that map a clause/window to a canonical outcome (deterministic).
OUTCOME_PHRASE_PATTERNS: tuple[tuple[str, CanonicalOutcome], ...] = (
    (r"\bqualify\b", "qualify_prospects"),
    (r"\bscore(?:s|d|ing)?\b", "qualify_prospects"),
    (r"\brank(?:s|ed|ing)?\b", "qualify_prospects"),
    (r"\brate(?:s|d|ing)?\b", "qualify_prospects"),
    (r"\bgrade(?:s|d|ing)?\b", "qualify_prospects"),
    (r"\bstrong(?:est)? prospects?\b", "qualify_prospects"),
    (r"\bbest (?:leads?|prospects?)\b", "qualify_prospects"),
    (r"\btop (?:leads?|prospects?|three|five|\d+)\b", "qualify_prospects"),
    (r"\bpick the (?:strongest|best)\b", "qualify_prospects"),
    (r"\bidentify .* (?:strong|best|top)\b", "qualify_prospects"),
)


@dataclass(frozen=True, slots=True)
class AbilityAliasHit:
    outcome: CanonicalOutcome
    source_text: str
    rule_id: str
    confidence: float


def match_outcome_phrases(text: str) -> list[AbilityAliasHit]:
    """Return deterministic outcome hits from ability vocabulary patterns."""

    if not text or not text.strip():
        return []
    hits: list[AbilityAliasHit] = []
    seen: set[str] = set()
    lower = text.lower()
    for phrase, outcome in ABILITY_OUTCOME_ALIASES.items():
        if phrase in lower and outcome not in seen:
            seen.add(outcome)
            hits.append(
                AbilityAliasHit(
                    outcome=outcome,
                    source_text=phrase,
                    rule_id="ability_vocab.phrase",
                    confidence=0.92,
                )
            )
    for pattern, outcome in OUTCOME_PHRASE_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is None or outcome in seen:
            continue
        seen.add(outcome)
        hits.append(
            AbilityAliasHit(
                outcome=outcome,
                source_text=match.group(0),
                rule_id="ability_vocab.pattern",
                confidence=0.9,
            )
        )
    return hits


def phrase_maps_to_outcome(clause: str) -> CanonicalOutcome | None:
    """Map a short unmatched clause to a canonical outcome when vocabulary allows."""

    stripped = " ".join(clause.strip().lower().split())
    if not stripped:
        return None
    if stripped in ABILITY_OUTCOME_ALIASES:
        return ABILITY_OUTCOME_ALIASES[stripped]
    # Strip leading "and "/trailing punctuation.
    cleaned = stripped.strip(" .,;:")
    if cleaned in ABILITY_OUTCOME_ALIASES:
        return ABILITY_OUTCOME_ALIASES[cleaned]
    for phrase, outcome in ABILITY_OUTCOME_ALIASES.items():
        if cleaned == phrase or cleaned.startswith(phrase) or phrase in cleaned:
            if len(cleaned) <= len(phrase) + 12:
                return outcome
    for pattern, outcome in OUTCOME_PHRASE_PATTERNS:
        if re.search(pattern, clause, flags=re.IGNORECASE):
            return outcome
    return None
