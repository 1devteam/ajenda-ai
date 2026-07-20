"""Deterministic plain-language → MissionIntent interpreter.

An LLM may later propose candidates, but acceptance remains deterministic.
This module never selects actions, grants credentials, or queues work.
"""

from __future__ import annotations

import re
from typing import Any

from backend.services.mission_composition.contracts import (
    INTERPRETER_VERSION,
    Clarification,
    MissionIntent,
    SuccessCriterion,
    TargetEntity,
)

_SEND_PATTERNS = (
    r"\bsend\b",
    r"\bsending\b",
    r"\bdeliver\b",
    r"\bdispatch\b",
    r"\bmail them\b",
)
_NO_SEND_PATTERNS = (
    r"before anything is sent",
    r"do not send",
    r"don't send",
    r"dont send",
    r"without sending",
    r"bring them to me",
    r"review before",
    r"draft only",
    r"prepare drafts",
    r"no send",
)
_DRAFT_PATTERNS = (
    r"\bdraft\b",
    r"introduction",
    r"outreach",
    r"personalized",
)
_QUALIFY_PATTERNS = (
    r"\bqualify\b",
    r"strong prospects",
    r"identify .* prospects",
    r"best (?:leads|prospects)",
)
_RESEARCH_PATTERNS = (
    r"\bresearch\b",
    r"\bfind\b",
    r"\bdiscover\b",
    r"companies in",
    r"prospects",
    r"competitors?",
    r"competors?",  # common misspelling
)
# Stop location capture before trailing mission verbs / qualifiers.
_LOCATION_TRAILING_STOP = re.compile(
    r"\s+\b(?:"
    r"identify|find|discover|and|with|for|to|that|who|which|"
    r"strong|best|top|draft|enrich|qualify|send|prepare|"
    r"prospects?|competitors?|competors?|leads?"
    r")\b",
    re.IGNORECASE,
)
_ENRICH_PATTERNS = (
    r"\benrich\b",
    r"contact details",
    r"find emails",
)
_CALENDAR_PATTERNS = (
    r"\bcalendar\b",
    r"calendar briefing",
    r"read calendar",
    r"upcoming (?:calendar )?commitments",
    r"meeting prep",
    r"meeting brief",
)
_COUNT_PATTERN = re.compile(r"\b(\d+|three|two|four|five|ten)\b", re.IGNORECASE)
_WORD_COUNTS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "ten": 10,
}
# Capture "{industry} companies in {location}" without swallowing leading verbs or trailing clauses.
_INDUSTRY_LOCATION = re.compile(
    r"(?:^|[\s,;:])(?P<industry>[A-Za-z][A-Za-z\-/]{1,40}(?:\s+[A-Za-z][A-Za-z\-/]{1,40}){0,3})"
    r"\s+companies\s+in\s+(?P<location>[A-Za-z][A-Za-z.\-]{1,40}(?:\s+[A-Za-z][A-Za-z.\-]{1,40}){0,3})"
    r"(?=$|[\s,;.:]|\band\b)",
    re.IGNORECASE,
)
_LEADING_VERB_WORDS = frozenset(
    {
        "research",
        "find",
        "discover",
        "identify",
        "search",
        "locate",
        "analyze",
        "study",
        "review",
        "target",
    }
)


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _extract_count(text: str) -> int | None:
    match = _COUNT_PATTERN.search(text)
    if match is None:
        return None
    raw = match.group(1).lower()
    if raw.isdigit():
        return int(raw)
    return _WORD_COUNTS.get(raw)


def _extract_target_entities(text: str) -> list[TargetEntity]:
    match = _INDUSTRY_LOCATION.search(text)
    if match is None:
        return []
    industry_tokens = [token for token in match.group("industry").strip().split() if token]
    while industry_tokens and industry_tokens[0].lower() in _LEADING_VERB_WORDS:
        industry_tokens.pop(0)
    industry = " ".join(industry_tokens).strip(" ,.;:")
    location = match.group("location").strip(" ,.;:")
    # "companies in Fayetteville AR identify three…" must not swallow verbs into location.
    stop = _LOCATION_TRAILING_STOP.search(f" {location}")
    if stop is not None:
        # stop matched with a leading space on the padded string; map back to location.
        cut = max(0, stop.start() - 1)
        location = location[:cut].strip(" ,.;:")
    if not industry or not location:
        return []
    return [
        TargetEntity(
            type="company",
            industry=industry,
            location=location,
        )
    ]


def interpret_instruction(
    instruction: str,
    *,
    profile_context: dict[str, Any] | None = None,
) -> MissionIntent:
    """Extract a candidate MissionIntent without granting execution authority."""

    text = instruction.strip()
    if not text:
        raise ValueError("instruction must be non-empty")

    profile_context = profile_context or {}
    lower = text.lower()
    outcomes: list[str] = []
    constraints: list[str] = []
    forbidden: list[str] = []
    clarifications: list[Clarification] = []
    success: list[SuccessCriterion] = []
    context_requirements: list[str] = []

    no_send = _contains_any(lower, _NO_SEND_PATTERNS)
    wants_send = _contains_any(lower, _SEND_PATTERNS) and not no_send
    wants_draft = _contains_any(lower, _DRAFT_PATTERNS)
    wants_qualify = _contains_any(lower, _QUALIFY_PATTERNS)
    wants_research = _contains_any(lower, _RESEARCH_PATTERNS)
    wants_enrich = _contains_any(lower, _ENRICH_PATTERNS) or (wants_draft and wants_qualify)
    wants_calendar = _contains_any(lower, _CALENDAR_PATTERNS)

    if wants_research:
        outcomes.append("research prospects")
    if wants_qualify:
        outcomes.append("qualify prospects")
    if wants_enrich:
        outcomes.append("enrich contacts")
    if wants_draft:
        outcomes.append("draft introductions")
    if wants_send:
        outcomes.append("send emails")
    if wants_calendar:
        outcomes.append("calendar briefing")

    if no_send or (wants_draft and not wants_send):
        constraints.append("Do not send messages")
        forbidden.append("send messages")
        forbidden.append("gtm.email_send")

    count = _extract_count(text)
    entities = _extract_target_entities(text)
    if entities:
        entity = entities[0]
        label = f"{entity.industry or 'target'} in {entity.location or 'specified market'}"
    else:
        label = "the requested market"

    if wants_research or wants_qualify:
        n = count or 3
        success.append(
            SuccessCriterion(
                description=f"{n} prospects contain company and qualification evidence for {label}",
                measurable=True,
            )
        )
    if wants_draft:
        n = count or 3
        success.append(
            SuccessCriterion(
                description=f"{n} personalized introduction drafts are ready for review",
                measurable=True,
            )
        )
    if not success:
        success.append(
            SuccessCriterion(
                description="Mission produces evidence-backed deliverables matching the stated objective",
                measurable=False,
            )
        )
        clarifications.append(
            Clarification(
                field="success_criteria",
                question="What concrete deliverables should mark this mission complete?",
                reason="Instruction did not state measurable success criteria.",
            )
        )

    if not outcomes:
        clarifications.append(
            Clarification(
                field="requested_outcomes",
                question="What business outcomes should this mission produce?",
                reason="Could not map the instruction to known research, qualify, enrich, draft, or send jobs.",
            )
        )

    approval = "review_before_external_action"
    if wants_send:
        approval = "explicit_approval_for_send"
    elif wants_draft:
        approval = "review_before_external_action"

    if profile_context.get("company") or profile_context.get("business_name"):
        context_requirements.append("business_profile")

    objective = text if len(text) <= 500 else text[:497] + "..."
    if wants_research and wants_draft and no_send:
        objective = f"Identify and prepare outreach for qualified {label} prospects without sending messages."

    return MissionIntent(
        objective=objective,
        requested_outcomes=outcomes,
        target_entities=entities,
        constraints=constraints,
        forbidden_outcomes=forbidden,
        success_criteria=success,
        urgency="normal",
        approval_preference=approval,
        budget_limits=None,
        context_requirements=context_requirements,
        ambiguity=clarifications,
        interpreter_version=INTERPRETER_VERSION,
    )
