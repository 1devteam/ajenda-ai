"""Deterministic plain-language → MissionIntent interpreter.

Emits canonical outcome IDs, structured quantity / send policy, and restatement
requirements. Does not select actions, grant credentials, or queue work.

Each compose submit is a standalone raw instruction — no client fragment merge.
"""

from __future__ import annotations

import re
from typing import Any

from backend.services.mission_composition.ability_vocab import (
    match_outcome_phrases,
    phrase_maps_to_outcome,
)
from backend.services.mission_composition.connector_capabilities import restatement_for_deferred_op
from backend.services.mission_composition.contracts import (
    CANONICAL_OUTCOMES,
    INTERPRETER_VERSION,
    CanonicalOutcome,
    Clarification,
    InterpretationEvidence,
    InterpretedClause,
    MissionIntent,
    SendPolicy,
    SuccessCriterion,
    TargetEntity,
)
from backend.services.mission_composition.interpretation.fuzzy import fuzzy_outcome_candidates
from backend.services.mission_composition.interpretation.normalize import normalize_instruction_text

_COMPONENTS_ACTIVE = ("regex_core", "ability_vocab")

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
_CONDITIONAL_SEND_PATTERNS = (
    r"send only after",
    r"after (?:i |my )?approv",
    r"once (?:i |you )?approv",
    r"until (?:i |you )?approv",
    r"hold until",
    r"nothing goes out without",
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
    # Ability vocab: score/rank/rate are qualify, not unmatched material.
    r"\bscore(?:s|d|ing)?\b",
    r"\brank(?:s|ed|ing)?\b",
    r"\brate(?:s|d|ing)?\b",
    r"\bgrade(?:s|d|ing)?\b",
    r"\btop (?:leads?|prospects?|three|five|\d+)\b",
    r"\bstrongest (?:leads?|prospects?|competitors?)\b",
    r"\bpick the (?:strongest|best)\b",
)
_RESEARCH_PATTERNS = (
    r"\bresearch\b",
    r"\bfind\b",
    r"\bdiscover\b",
    r"companies in",
    r"prospects",
    r"competitors?",
    r"competors?",
)
_LOCATION_TRAILING_STOP = re.compile(
    r"\s+\b(?:"
    r"identify|find|discover|and|with|for|to|that|who|which|"
    r"strong|best|top|draft|enrich|qualify|send|prepare|score|rank|"
    r"prospects?|competitors?|competors?|leads?"
    r")\b",
    re.IGNORECASE,
)
_ENRICH_PATTERNS = (
    r"\benrich\b",
    r"contact details",
    r"contact info(?:rmation)?",
    r"collect (?:contact|email|phone)",
    r"gather (?:contact|email|phone)",
    r"find (?:emails?|phone numbers?|contact)",
    r"look up (?:emails?|contact)",
)
# Read-oriented calendar only. Imperative "schedule a meeting" is not events_read.
_CALENDAR_PATTERNS = (
    r"\bcalend[ae]r\b",
    r"calendar briefing",
    r"read calend[ae]r",
    r"google calend[ae]r",
    r"\bagenda\b",
    r"what(?:'s| is) on my (?:calend[ae]r|schedule)",
    r"what do i have (?:scheduled|on my calend[ae]r)",
    r"what(?:'s| is) scheduled\b",
    r"upcoming (?:calendar )?commitments",
    r"meeting prep",
    r"meeting brief",
    r"show (?:me )?(?:my )?(?:calend[ae]r|schedule)",
    r"check (?:my )?(?:calend[ae]r|schedule)",
    r"\bevents?\b.*\bcalend[ae]r\b",
    r"\bcalend[ae]r\b.*\bevents?\b",
)
_CALENDAR_MUTATION_PATTERNS = (
    r"\bschedule (?:a |an )?(?:meeting|call|event|appointment)\b",
    r"\bbook (?:a |an )?(?:meeting|call|event|appointment)\b",
    r"\bcreate (?:a |an )?(?:calendar )?(?:event|meeting)\b",
    r"\badd (?:a |an )?(?:meeting|event) to (?:my )?(?:calend[ae]r|schedule)\b",
    r"\bdelete\b.{0,40}\b(?:calend[ae]r|event|meeting|appointment)\b",
    r"\bcancel\b.{0,40}\b(?:calend[ae]r|event|meeting|appointment)\b",
    r"\breschedule\b.{0,40}\b(?:calend[ae]r|event|meeting|appointment)\b",
    r"\bupdate\b.{0,40}\b(?:calend[ae]r|event|meeting|appointment)\b",
    r"\bremove\b.{0,40}\b(?:calend[ae]r|events?|meetings?)\b",
    r"\bmove\b.{0,40}\b(?:meeting|event|appointment)\b",
)
# Mutation verbs only — naming HubSpot/CRM as a read source must not imply upsert.
_CRM_UPDATE_PATTERNS = (
    r"\bupdate (?:the )?(?:crm|pipeline|hubspot)\b",
    r"\blog (?:to |in |into )?(?:the )?crm\b",
    r"\blogs? (?:activity|to crm)\b",
    r"\bupsert\b",
    r"\bwrite (?:to |into )?(?:the )?crm\b",
    r"\bsync (?:to |into )?(?:the )?(?:crm|hubspot|contacts?)\b",
    r"\bpush (?:to |into )?(?:the )?(?:crm|hubspot|contacts?)\b",
    r"\badd (?:them|it|these|those|each|leads?|prospects?|companies)?\s*(?:to|into)\s+(?:my\s+)?(?:crm\s+)?contacts?\b",
    r"\bsave (?:them|it|these|those|each|leads?|prospects?)?\s*(?:to|into|in)\s+(?:my\s+)?(?:crm\s+)?contacts?\b",
    r"\badd (?:them|it|these|those)\s+to\s+(?:the\s+)?(?:crm|hubspot|pipeline)\b",
    r"\bsave (?:them|it|these|those)\s+to\s+(?:the\s+)?(?:crm|hubspot|pipeline)\b",
    # Natural "save / add to contacts" language (Google Contacts, CRM, or internal contact book).
    r"\bput (?:them|it|these|those)\s+(?:in|into)\s+(?:my\s+)?(?:crm\s+)?contacts?\b",
    r"\bcreate (?:crm )?(?:records?|contacts?)\b",
)
_CRM_NEGATION_PATTERNS = (
    r"\b(?:do not|don't|dont|never|without)\s+add\b.{0,40}\bcontacts?\b",
    r"\b(?:do not|don't|dont|never|without)\s+save\b.{0,40}\bcontacts?\b",
    r"\b(?:do not|don't|dont|never|without)\s+(?:add|save|sync|push|write|update|log|upsert|create)\b.{0,48}\b(?:crm|hubspot|pipeline|contacts?)\b",
    r"\bno\s+(?:crm|contact)\s+(?:updates?|writes?|saves?)\b",
    r"\bwithout\s+(?:adding|saving)\s+(?:them\s+)?to\s+contacts?\b",
)
# Publish/post verbs only — "prospects on LinkedIn" is research, not publishing.
_PUBLISH_PATTERNS = (
    r"\bpublish\b",
    r"\bpost(?:ing)? (?:to|on) (?:linkedin|social|twitter|x)\b",
    r"\bpost(?:ing)? .{0,48}\b(?:to|on) (?:linkedin|social|twitter|x)\b",
    r"\bshare (?:to|on) (?:linkedin|social)\b",
    r"\bpost (?:an? )?(?:update|announcement|message) (?:to|on)\b",
    r"\bsocial media post",
)
_PUBLISH_NEGATION_PATTERNS = (
    r"\b(?:do not|don't|dont|never|without)\s+publish\b",
    r"\b(?:do not|don't|dont|never|without)\s+post\b",
    r"\b(?:do not|don't|dont|never)\s+share\b.{0,24}\b(?:linkedin|social|twitter|x)\b",
    r"\bno\s+(?:social\s+)?(?:publishing|posts?)\b",
)
# Publish that must wait on upstream research outputs (not standalone copy).
_PUBLISH_RESULT_BASED = re.compile(
    r"\b(?:post|publish|share)\s+(?:the\s+)?(?:results?|findings?|them)\b",
    re.IGNORECASE,
)
_COUNT_PATTERN = re.compile(r"\b(\d+|three|two|four|five|ten)\b", re.IGNORECASE)
_WORD_COUNTS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "ten": 10,
}
_MONTH_NAME = (
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
# Strip calendar dates so "July 28 2026" is not quantity 28.
_DATE_SPAN = re.compile(
    rf"\b(?:{_MONTH_NAME})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{4}})?\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    re.IGNORECASE,
)
_INDUSTRY_LOCATION = re.compile(
    r"(?:^|[\s,;:])(?P<industry>[A-Za-z][A-Za-z\-/]{1,40}(?:\s+[A-Za-z][A-Za-z\-/]{1,40}){0,3})"
    r"\s+companies\s+in\s+(?P<location>[A-Za-z][A-Za-z.\-]{1,40}(?:\s+[A-Za-z][A-Za-z.\-]{1,40}){0,3})"
    r"(?=$|[\s,;.:]|\band\b)",
    re.IGNORECASE,
)
# "competitors of Acme Roofing in Northwest Arkansas" (prefer with location)
_COMPETITORS_OF_IN = re.compile(
    r"\bcompetitors?\s+of\s+"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9.&'\-/]*(?:\s+[A-Za-z0-9][A-Za-z0-9.&'\-/]*){0,5})"
    r"\s+in\s+"
    r"(?P<location>[A-Za-z][A-Za-z.\-]{1,40}(?:\s+[A-Za-z][A-Za-z.\-]{1,40}){0,4})"
    r"(?=$|[\s,;.:]|\band\b)",
    re.IGNORECASE,
)
# "competitors of Smith HVAC" (no location)
_COMPETITORS_OF_BARE = re.compile(
    r"\bcompetitors?\s+of\s+"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9.&'\-/]*(?:\s+[A-Za-z0-9][A-Za-z0-9.&'\-/]*){0,5})"
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
# Strip quantity words so "three roofing companies" → industry "roofing".
_LEADING_QUANTITY_WORDS = frozenset(
    {
        "a",
        "an",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "several",
        "some",
        "few",
        "many",
    }
)
_FRAGMENT_HINTS = (
    r"^complete when\b",
    r"^when the email is sent\b",
    r"^just\b",
    r"^\d+\s*(companies|prospects|leads)?\.?$",
    r"^(two|three|four|five|ten)\s*(companies|prospects|leads)?\.?$",
    r"^[A-Za-z][A-Za-z.\-\s]{1,40}$",
)
_CLAUSE_SPLIT = re.compile(r"\s*(?:,|\band\b|;)\s*", re.IGNORECASE)


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


_MONTH_NAME = (
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_DATE_SPAN = re.compile(
    rf"\b(?:{_MONTH_NAME})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{4}})?\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    re.IGNORECASE,
)


def _extract_count(text: str) -> int | None:
    """Extract prospect quantity — never calendar day numbers or years."""

    cleaned = _DATE_SPAN.sub(" ", text)

    cleaned = re.sub(r"\b20\d{2}\b", " ", cleaned)
    match = _COUNT_PATTERN.search(cleaned)
    if match is None:
        return None
    raw = match.group(1).lower()
    if raw.isdigit():
        value = int(raw)
        # Prospect quantities are small; large bare integers are not counts here.

        if value > 50:
            return None
        return value
    return _WORD_COUNTS.get(raw)


def _trim_location(location: str) -> str:
    location = (location or "").strip(" ,.;:")
    stop = _LOCATION_TRAILING_STOP.search(f" {location}")
    if stop is not None:
        cut = max(0, stop.start() - 1)
        location = location[:cut].strip(" ,.;:")
    return location


def _extract_competitors_of(text: str) -> list[TargetEntity]:
    """Extract 'competitors of {Company} [in {Location}]' as a structured target."""

    match = _COMPETITORS_OF_IN.search(text)
    location: str | None = None
    if match is not None:
        name = match.group("name").strip(" ,.;:")
        location = _trim_location(match.group("location"))
    else:
        match = _COMPETITORS_OF_BARE.search(text)
        if match is None:
            return []
        name = match.group("name").strip(" ,.;:")
        # Guard against swallowing trailing verbs when "in" is absent.
        name_stop = _LOCATION_TRAILING_STOP.search(f" {name}")
        if name_stop is not None:
            cut = max(0, name_stop.start() - 1)
            name = name[:cut].strip(" ,.;:")
    if not name or len(name) < 2:
        return []
    # Infer a light industry hint from the last name token when it is a trade word.
    industry: str | None = None
    tokens = name.split()
    if tokens:
        last = tokens[-1].lower()
        if last in {
            "roofing",
            "plumbing",
            "hvac",
            "electrical",
            "landscaping",
            "construction",
            "dentistry",
            "dental",
            "legal",
            "law",
            "insurance",
            "realty",
            "software",
        }:
            industry = tokens[-1]
    return [
        TargetEntity(
            type="competitor_set",
            name=name,
            industry=industry,
            location=location or None,
            attributes={
                "research_mode": "competitors",
                "anchor_company": name,
            },
            provenance="explicit",
            confidence=0.95,
        )
    ]


def _extract_target_entities(text: str) -> list[TargetEntity]:
    competitors = _extract_competitors_of(text)
    if competitors:
        return competitors
    match = _INDUSTRY_LOCATION.search(text)
    if match is None:
        return []
    industry_tokens = [token for token in match.group("industry").strip().split() if token]
    while industry_tokens and industry_tokens[0].lower() in _LEADING_VERB_WORDS:
        industry_tokens.pop(0)
    while industry_tokens and (industry_tokens[0].lower() in _LEADING_QUANTITY_WORDS or industry_tokens[0].isdigit()):
        industry_tokens.pop(0)
    industry = " ".join(industry_tokens).strip(" ,.;:")
    location = _trim_location(match.group("location"))
    if not industry or not location:
        return []
    return [
        TargetEntity(
            type="company",
            industry=industry,
            location=location,
            provenance="explicit",
            confidence=0.95,
        )
    ]


def _restatement(
    *,
    field: str,
    understood: str | None,
    missing: str,
    include_instruction: str,
    reason: str,
) -> Clarification:
    parts: list[str] = []
    if understood:
        parts.append(f"I understood: {understood}.")
    parts.append(f"I cannot compose this mission reliably because {missing}.")
    parts.append(f"Please restate the complete mission and include {include_instruction}.")
    return Clarification(field=field, question=" ".join(parts), reason=reason)


def _looks_like_fragment(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 12:
        return True
    if len(stripped.split()) <= 6 and _contains_any(stripped.lower(), _FRAGMENT_HINTS):
        return True
    if len(stripped) < 80 and not _contains_any(
        stripped.lower(),
        _RESEARCH_PATTERNS + _DRAFT_PATTERNS + _SEND_PATTERNS + _QUALIFY_PATTERNS + _CALENDAR_PATTERNS,
    ):
        return True
    return False


def _evidence(
    *,
    field_path: str,
    source: str,
    source_text: str | None = None,
    normalized_value: str | None = None,
    confidence: float = 1.0,
    rule_id: str | None = None,
) -> InterpretationEvidence:
    return InterpretationEvidence(
        field_path=field_path,
        source=source,  # type: ignore[arg-type]
        source_text=source_text,
        normalized_value=normalized_value,
        confidence=confidence,
        rule_id=rule_id,
        interpreter_version=INTERPRETER_VERSION,
        components_active=list(_COMPONENTS_ACTIVE),
    )


def _success_for_outcomes(
    *,
    outcomes: list[CanonicalOutcome],
    quantity: int | None,
    quantity_source: str,
    label: str,
) -> list[SuccessCriterion]:
    """Display completion text from job contracts — not a data transport."""

    n = quantity if quantity is not None else 3
    success: list[SuccessCriterion] = []
    if "research_prospects" in outcomes or "qualify_prospects" in outcomes:
        qty_note = f"{n}" if quantity is not None else f"{n} (system default)"
        if quantity_source == "system_default":
            qty_note = f"{n} (system default)"
        success.append(
            SuccessCriterion(
                description=f"{qty_note} prospects contain company and qualification evidence for {label}",
                measurable=True,
            )
        )
    if "enrich_contacts" in outcomes:
        success.append(
            SuccessCriterion(
                description=f"{n} prospects include contact enrichment evidence",
                measurable=True,
            )
        )
    if "prepare_outreach" in outcomes:
        success.append(
            SuccessCriterion(
                description=f"{n} personalized introduction drafts are ready for review",
                measurable=True,
            )
        )
    if "send_outreach" in outcomes:
        success.append(
            SuccessCriterion(
                description="Provider returns an accepted-send result or message identifier for each authorized send",
                measurable=True,
            )
        )
    if "read_calendar" in outcomes:
        success.append(
            SuccessCriterion(
                description="Requested calendar results are returned with provider evidence",
                measurable=True,
            )
        )
    if "update_crm" in outcomes:
        success.append(
            SuccessCriterion(
                description="CRM record changes are confirmed by provider response or readback",
                measurable=True,
            )
        )
    if "publish_content" in outcomes:
        success.append(
            SuccessCriterion(
                description="Provider confirms the social post was accepted or returns a publish identifier",
                measurable=True,
            )
        )
    return success


def _segment_clauses(text: str) -> list[str]:
    parts = [p.strip(" ,.;") for p in _CLAUSE_SPLIT.split(text) if p and p.strip(" ,.;")]
    return parts if parts else [text.strip()]


def _classify_clause(clause: str) -> tuple[list[CanonicalOutcome], bool, bool]:
    """Return (outcomes, material, recognized)."""

    lower = clause.lower()
    outcomes: list[CanonicalOutcome] = []
    if _contains_any(lower, _RESEARCH_PATTERNS):
        outcomes.append("research_prospects")
    if _contains_any(lower, _QUALIFY_PATTERNS):
        outcomes.append("qualify_prospects")
    if _contains_any(lower, _ENRICH_PATTERNS):
        outcomes.append("enrich_contacts")
    if _contains_any(lower, _DRAFT_PATTERNS):
        outcomes.append("prepare_outreach")
    if _contains_any(lower, _SEND_PATTERNS) and not _contains_any(lower, _NO_SEND_PATTERNS):
        outcomes.append("send_outreach")
    if _contains_any(lower, _CALENDAR_PATTERNS):
        outcomes.append("read_calendar")
    if _contains_any(lower, _CRM_UPDATE_PATTERNS) and not _contains_any(lower, _CRM_NEGATION_PATTERNS):
        outcomes.append("update_crm")
    if _contains_any(lower, _PUBLISH_PATTERNS) and not _contains_any(lower, _PUBLISH_NEGATION_PATTERNS):
        outcomes.append("publish_content")
    # Ability vocabulary: map short clauses like "score them" before marking unmatched.
    vocab_outcome = phrase_maps_to_outcome(clause)
    if vocab_outcome is not None and vocab_outcome not in outcomes:
        outcomes.append(vocab_outcome)

    material = bool(outcomes) or _contains_any(
        lower,
        _NO_SEND_PATTERNS
        + _CONDITIONAL_SEND_PATTERNS
        + _CRM_UPDATE_PATTERNS
        + _CRM_NEGATION_PATTERNS
        + _PUBLISH_PATTERNS
        + _PUBLISH_NEGATION_PATTERNS
        + (
            r"\bapprov",
            r"\bdelet",
            r"\bcharg",
            r"\binvoice",
            r"\bfax\b",
            r"\bpurchase order\b",
            r"\bwire (?:transfer|money)\b",
            r"\btransfer funds\b",
            r"\bpay\b",
            r"\brefund\b",
            r"\bdelete\b",
            r"\bterminate\b",
        ),
    )
    # Bare location/count fragments treated as material when short.
    if not material and (re.search(r"\b\d+\b", lower) or len(clause.split()) <= 4):
        material = True
    recognized = bool(outcomes) or _contains_any(
        lower,
        _NO_SEND_PATTERNS + _CONDITIONAL_SEND_PATTERNS + _CRM_NEGATION_PATTERNS,
    )
    # Industry+location span is recognized material even without a verb.
    if _INDUSTRY_LOCATION.search(clause):
        material = True
        recognized = True
    return outcomes, material, recognized


def interpret_instruction(
    instruction: str,
    *,
    profile_context: dict[str, Any] | None = None,
    spelling_enabled: bool | None = None,
    fuzzy_enabled: bool | None = None,
) -> MissionIntent:
    """Extract a candidate MissionIntent without granting execution authority."""

    raw_instruction = instruction
    text = instruction.strip()
    if not text:
        raise ValueError("instruction must be non-empty")

    # Settings are optional so unit tests stay free of full app config.
    if spelling_enabled is None or fuzzy_enabled is None:
        try:
            from backend.app.config import get_settings

            settings = get_settings()
            if spelling_enabled is None:
                spelling_enabled = bool(settings.mission_interpreter_spelling_enabled)
            if fuzzy_enabled is None:
                fuzzy_enabled = bool(settings.mission_interpreter_fuzzy_enabled)
        except Exception:
            spelling_enabled = True if spelling_enabled is None else spelling_enabled
            fuzzy_enabled = True if fuzzy_enabled is None else fuzzy_enabled

    norm = normalize_instruction_text(text, spelling_enabled=bool(spelling_enabled))
    text = norm.normalized
    components_active: list[str] = list(dict.fromkeys([*_COMPONENTS_ACTIVE, *norm.components_active]))

    profile_context = profile_context or {}
    lower = text.lower()
    evidence: list[InterpretationEvidence] = []
    clarifications: list[Clarification] = []
    context_requirements: list[str] = []
    for correction in norm.spelling_corrections:
        evidence.append(
            _evidence(
                field_path="normalized_instruction",
                source="normalized",
                source_text=correction.original,
                normalized_value=correction.replacement,
                confidence=correction.confidence,
                rule_id=f"spelling.{correction.source}",
            )
        )

    no_send = _contains_any(lower, _NO_SEND_PATTERNS)
    conditional_send = _contains_any(lower, _CONDITIONAL_SEND_PATTERNS)
    wants_send = _contains_any(lower, _SEND_PATTERNS) and not no_send and not conditional_send
    wants_draft = _contains_any(lower, _DRAFT_PATTERNS)
    wants_qualify = _contains_any(lower, _QUALIFY_PATTERNS)
    wants_research = _contains_any(lower, _RESEARCH_PATTERNS)
    # Enrich only when explicitly requested — not invented from draft+qualify.
    wants_enrich = _contains_any(lower, _ENRICH_PATTERNS)
    wants_calendar = _contains_any(lower, _CALENDAR_PATTERNS)
    no_crm = _contains_any(lower, _CRM_NEGATION_PATTERNS)
    wants_crm = _contains_any(lower, _CRM_UPDATE_PATTERNS) and not no_crm
    no_publish = _contains_any(lower, _PUBLISH_NEGATION_PATTERNS)
    wants_publish = _contains_any(lower, _PUBLISH_PATTERNS) and not no_publish
    publish_result_based = _PUBLISH_RESULT_BASED.search(lower) is not None

    outcomes: list[CanonicalOutcome] = []
    if wants_research:
        outcomes.append("research_prospects")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.research_prospects",
                source="inferred_deterministic",
                source_text=text[:200],
                normalized_value="research_prospects",
                confidence=0.9,
                rule_id="alias.research",
            )
        )
    if wants_qualify:
        outcomes.append("qualify_prospects")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.qualify_prospects",
                source="inferred_deterministic",
                source_text=text[:200],
                normalized_value="qualify_prospects",
                confidence=0.9,
                rule_id="alias.qualify",
            )
        )
    # Ability vocabulary layer (score/rank/… → canonical outcomes).
    for vocab_hit in match_outcome_phrases(text):
        if vocab_hit.outcome not in outcomes:
            outcomes.append(vocab_hit.outcome)
            evidence.append(
                _evidence(
                    field_path=f"requested_outcomes.{vocab_hit.outcome}",
                    source="inferred_deterministic",
                    source_text=vocab_hit.source_text,
                    normalized_value=vocab_hit.outcome,
                    confidence=vocab_hit.confidence,
                    rule_id=vocab_hit.rule_id,
                )
            )
            if vocab_hit.outcome == "qualify_prospects":
                wants_qualify = True
    if wants_enrich:
        outcomes.append("enrich_contacts")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.enrich_contacts",
                source="explicit",
                normalized_value="enrich_contacts",
                confidence=0.95,
                rule_id="alias.enrich",
            )
        )
    if wants_draft:
        outcomes.append("prepare_outreach")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.prepare_outreach",
                source="inferred_deterministic",
                normalized_value="prepare_outreach",
                confidence=0.9,
                rule_id="alias.draft",
            )
        )
    if wants_send:
        outcomes.append("send_outreach")
        evidence.append(
            _evidence(
                field_path="requested_outcomes.send_outreach",
                source="explicit",
                normalized_value="send_outreach",
                confidence=0.95,
                rule_id="alias.send",
            )
        )
    if wants_calendar:
        outcomes.append("read_calendar")
    if wants_crm:
        outcomes.append("update_crm")
    if wants_publish:
        outcomes.append("publish_content")

    # Calendar write/create language is understood via connector schema but not runtime-bound.
    calendar_write_requested = _contains_any(lower, _CALENDAR_MUTATION_PATTERNS)
    calendar_read_intent = bool(
        re.search(
            r"\b(?:what(?:'s| is)|show|check|read|upcoming|brief(?:ing)?)\b.{0,40}\b(?:calend[ae]r|schedule)\b"
            r"|\b(?:calend[ae]r|schedule)\b.{0,40}\b(?:what|show|check|read|upcoming|brief)\b",
            lower,
            flags=re.IGNORECASE,
        )
    )
    if calendar_write_requested and "read_calendar" in outcomes and not calendar_read_intent:
        outcomes = [o for o in outcomes if o != "read_calendar"]

    # Optional fuzzy candidates only for unresolved outcome language (never ability select).
    fuzzy_already = set(outcomes)
    if calendar_write_requested and not calendar_read_intent:
        # Do not let fuzzy re-introduce read_calendar from "my calendar" / "schedule" aliases.
        fuzzy_already.add("read_calendar")
    fuzzy_hits, fuzzy_components = fuzzy_outcome_candidates(
        text,
        enabled=bool(fuzzy_enabled),
        already=fuzzy_already,
    )
    components_active.extend(c for c in fuzzy_components if c not in components_active)
    medium_fuzzy: list[str] = []
    for fuzzy_hit in fuzzy_hits:
        if fuzzy_hit.band == "high" and fuzzy_hit.outcome not in outcomes:
            if calendar_write_requested and not calendar_read_intent and fuzzy_hit.outcome == "read_calendar":
                continue
            outcomes.append(fuzzy_hit.outcome)
            evidence.append(
                _evidence(
                    field_path=f"requested_outcomes.{fuzzy_hit.outcome}",
                    source="inferred_fuzzy",
                    source_text=fuzzy_hit.matched_alias,
                    normalized_value=fuzzy_hit.outcome,
                    confidence=min(0.89, fuzzy_hit.score / 100.0),
                    rule_id="fuzzy.outcome_high",
                )
            )
        elif fuzzy_hit.band == "medium":
            medium_fuzzy.append(f"{fuzzy_hit.matched_alias}≈{fuzzy_hit.outcome}({fuzzy_hit.score:.0f})")

    # Structured send policy (authoritative for downstream).
    # Conditional approval outranks bare "do not send" when both appear
    # ("do not send anything until I approve").
    constraints: list[str] = []
    forbidden: list[str] = []
    if no_crm:
        forbidden.append("gtm.crm_upsert")
        constraints.append("Do not write contacts or CRM records")
        if "update_crm" in outcomes:
            outcomes = [o for o in outcomes if o != "update_crm"]
    if no_publish:
        forbidden.append("gtm.social_publish")
        constraints.append("Do not publish or post to social channels")
        if "publish_content" in outcomes:
            outcomes = [o for o in outcomes if o != "publish_content"]
    if conditional_send:
        send_policy = SendPolicy(
            mode="conditional",
            condition="approval",
            source="explicit",
            confidence=0.95,
            rule_id="policy.send_after_approval",
        )
        constraints.append("Send only after approval")
        forbidden.append("gtm.email_send")
        evidence.append(
            _evidence(
                field_path="send_policy",
                source="explicit",
                normalized_value="conditional:approval",
                confidence=0.95,
                rule_id="policy.send_after_approval",
            )
        )
        # Desired but deferred — do not emit send_outreach as ready outcome.
        if "send_outreach" in outcomes:
            outcomes = [o for o in outcomes if o != "send_outreach"]
    elif no_send or (wants_draft and not wants_send):
        send_policy = SendPolicy(
            mode="forbid",
            condition="none",
            source="explicit" if no_send else "inferred_deterministic",
            confidence=0.98 if no_send else 0.9,
            rule_id="negation.no_send" if no_send else "negation.draft_only",
        )
        constraints.append("Do not send messages")
        forbidden.extend(["gtm.email_send"])
        if "send_outreach" in outcomes:
            outcomes = [o for o in outcomes if o != "send_outreach"]
        evidence.append(
            _evidence(
                field_path="send_policy",
                source=send_policy.source,
                normalized_value="forbid",
                confidence=send_policy.confidence,
                rule_id=send_policy.rule_id,
            )
        )
    elif wants_send:
        send_policy = SendPolicy(
            mode="allow",
            condition="none",
            source="explicit",
            confidence=0.9,
            rule_id="policy.send_allow",
        )
        evidence.append(
            _evidence(
                field_path="send_policy",
                source="explicit",
                normalized_value="allow",
                confidence=0.9,
                rule_id="policy.send_allow",
            )
        )
    else:
        send_policy = SendPolicy(mode="unknown", condition="none", source="unresolved", confidence=0.0)

    count = _extract_count(text)
    if count is not None:
        quantity: int | None = count
        quantity_provenance = "explicit"
        evidence.append(
            _evidence(
                field_path="requested_quantity",
                source="explicit",
                source_text=str(count),
                normalized_value=str(count),
                confidence=0.95,
                rule_id="entity.quantity",
            )
        )
    elif outcomes and any(o in outcomes for o in ("research_prospects", "qualify_prospects")):
        # Default quantity only for low-risk prospect research — not drafts/calendar.
        quantity = 3
        quantity_provenance = "system_default"
        evidence.append(
            _evidence(
                field_path="requested_quantity",
                source="system_default",
                normalized_value="3",
                confidence=0.55,
                rule_id="default.quantity_3",
            )
        )
    else:
        quantity = None
        quantity_provenance = None

    entities = _extract_target_entities(text)
    # Named email recipients (draft-to-X without inventing discovery).
    for email_match in re.finditer(
        r"\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b",
        text,
    ):
        email = email_match.group(1)
        if not any((e.email or "").lower() == email.lower() for e in entities):
            entities.append(
                TargetEntity(
                    type="recipient",
                    name=email.split("@")[0],
                    email=email,
                    provenance="explicit",
                    confidence=0.95,
                )
            )
            evidence.append(
                _evidence(
                    field_path="target_entities.email",
                    source="explicit",
                    source_text=email,
                    normalized_value=email,
                    confidence=0.95,
                    rule_id="entity.email_recipient",
                )
            )
    if entities and entities[0].type == "competitor_set" and entities[0].name:
        evidence.append(
            _evidence(
                field_path="target_entities[0]",
                source="explicit",
                source_text=(
                    f"competitors of {entities[0].name}"
                    + (f" in {entities[0].location}" if entities[0].location else "")
                ),
                normalized_value=f"competitors_of|{entities[0].name}|{entities[0].location or ''}",
                confidence=entities[0].confidence,
                rule_id="entity.competitors_of",
            )
        )
        label = f"competitors of {entities[0].name}" + (
            f" in {entities[0].location}" if entities[0].location else ""
        )
    elif entities and entities[0].industry:
        evidence.append(
            _evidence(
                field_path="target_entities[0]",
                source="explicit",
                source_text=f"{entities[0].industry} in {entities[0].location}",
                normalized_value=f"{entities[0].industry}|{entities[0].location}",
                confidence=entities[0].confidence,
                rule_id="entity.industry_location",
            )
        )
        label = f"{entities[0].industry or 'target'} in {entities[0].location or 'specified market'}"
    elif entities and entities[0].email:
        label = entities[0].email
    elif entities and entities[0].name:
        label = entities[0].name
    else:
        label = "the requested market"

    # Clause coverage
    clause_models: list[InterpretedClause] = []
    unmatched: list[InterpretedClause] = []
    for index, clause_text in enumerate(_segment_clauses(text)):
        mapped, material, recognized = _classify_clause(clause_text)
        # Non-material filler: short politeness without risk keywords.
        if not material and len(clause_text.split()) <= 3:
            status = "non_material"
            material = False
            recognized = True
        elif recognized:
            status = "recognized"
        elif material:
            status = "unmatched"
        else:
            status = "non_material"
        clause = InterpretedClause(
            clause_id=f"c{index}",
            text=clause_text[:2000],
            status=status,  # type: ignore[arg-type]
            material=material,
            mapped_outcomes=mapped,
            reason=None if recognized else "No deterministic outcome or policy mapping",
        )
        clause_models.append(clause)
        if status == "unmatched" and material:
            unmatched.append(clause)

    material_total = sum(1 for c in clause_models if c.material)
    material_ok = sum(1 for c in clause_models if c.material and c.status == "recognized")
    coverage = (material_ok / material_total) if material_total else (1.0 if outcomes else 0.0)

    success = _success_for_outcomes(
        outcomes=outcomes,
        quantity=quantity,
        quantity_source=quantity_provenance or "unresolved",
        label=label,
    )

    understood_bits = [o.replace("_", " ") for o in outcomes]
    if entities:
        understood_bits.append(f"target {label}")
    if quantity is not None and quantity_provenance == "explicit":
        understood_bits.append(f"quantity {quantity}")
    understood = ", ".join(understood_bits) if understood_bits else None

    if not outcomes:
        if calendar_write_requested:
            # Connector schema clarification (calendar_write) is enough — avoid dual restatements.
            pass
        elif _looks_like_fragment(text):
            clarifications.append(
                _restatement(
                    field="requested_outcomes",
                    understood=None,
                    missing="this looks like a partial answer, not a complete mission instruction",
                    include_instruction=(
                        "the full objective, target market or scope, deliverable, "
                        "and whether sending or other external actions are permitted"
                    ),
                    reason=(
                        "Fragment answers cannot be merged into a prior MissionIntent; "
                        "each compose submit is a standalone raw instruction."
                    ),
                )
            )
        else:
            clarifications.append(
                _restatement(
                    field="requested_outcomes",
                    understood=None,
                    missing="a business outcome could not be determined",
                    include_instruction=(
                        "what Ajenda should produce "
                        "(for example research prospects, qualify leads, prepare outreach, "
                        "send email only after approval, or calendar briefing)"
                    ),
                    reason="Could not map the instruction to a canonical business outcome.",
                )
            )
    elif not success:
        clarifications.append(
            _restatement(
                field="success_criteria",
                understood=understood,
                missing="a measurable completion result could not be determined",
                include_instruction="the deliverable or evidence that should mark the mission complete",
                reason="Mapped outcomes did not yield a completion contract.",
            )
        )

    if unmatched:
        missing_bits = "; ".join(c.text[:120] for c in unmatched[:3])
        clarifications.append(
            _restatement(
                field="clause_coverage",
                understood=understood,
                missing=f"one or more material clauses were not understood ({missing_bits})",
                include_instruction=(
                    "those clauses rewritten in plain business language "
                    "(for example CRM updates, publishing, or external actions)"
                ),
                reason="Unmatched material clauses must not be silently dropped.",
            )
        )
        coverage = min(coverage, max(0.0, (material_ok) / max(material_total, 1)))

    if medium_fuzzy and not outcomes:
        clarifications.append(
            _restatement(
                field="requested_outcomes",
                understood=None,
                missing=(
                    "only medium-confidence phrase matches were found "
                    f"({'; '.join(medium_fuzzy[:3])}); outcomes must be clearer"
                ),
                include_instruction=(
                    "explicit business outcomes using plain language "
                    "(research, qualify, prepare outreach, send after approval, calendar)"
                ),
                reason="Medium-confidence fuzzy matches must not authorize outcomes.",
            )
        )

    # Imperative calendar create/update/delete — intent understood, op deferred by connector schema.
    if calendar_write_requested:
        connector_note = restatement_for_deferred_op(connector_id="google_calendar", op="write")
        missing = connector_note or (
            "creating, updating, rescheduling, or deleting calendar events is not a composed "
            "runtime outcome yet (only calendar read/briefing is supported)"
        )
        clarifications.append(
            _restatement(
                field="calendar_write",
                understood=understood,
                missing=missing[:500],
                include_instruction=(
                    "whether to read existing calendar events instead, or omit calendar mutations from this mission"
                ),
                reason=(
                    "Connector capability schema: google_calendar write is deferred; "
                    "mutation language must not silently map to google_calendar.events_read."
                ),
            )
        )

    # Tag result-based publish so planners can expand research deps and bind content.
    if publish_result_based and "publish_content" in outcomes:
        if entities:
            entities = [
                entity.model_copy(update={"attributes": {**(entity.attributes or {}), "publish_result_based": True}})
                for entity in entities
            ]
        else:
            entities = [
                TargetEntity(
                    type="publish_context",
                    provenance="inferred_deterministic",
                    confidence=0.9,
                    attributes={"publish_result_based": True},
                )
            ]

    emailish = wants_draft or "email" in lower or "message" in lower
    if (
        emailish
        and send_policy.mode == "unknown"
        and not wants_draft
        and not wants_send
        and "send_outreach" not in outcomes
    ):
        clarifications.append(
            _restatement(
                field="send_permission",
                understood=understood,
                missing="the instruction does not clearly state whether Ajenda should prepare email only or also send it",
                include_instruction="whether sending is permitted or drafts must stay for review only",
                reason="External send permission is material and ambiguous.",
            )
        )

    # Prospect discovery without target scope (industry/location/competitors) — job-specific.
    if "research_prospects" in outcomes and not entities:
        # Allow trend-like research if no company-hunt shape; only restatement when
        # "companies" / prospect hunt language implies a bounded market.
        if re.search(r"\bcompanies\b|\bprospects\b|\bleads\b|\bcompetitors?\b", lower):
            clarifications.append(
                _restatement(
                    field="target_scope",
                    understood=understood,
                    missing="the target market is missing or could not be extracted",
                    include_instruction=(
                        "the industry or company type and the city/region, "
                        "or competitors of a named company in a location"
                    ),
                    reason="Prospect discovery requires a usable target scope.",
                )
            )

    approval = "review_before_external_action"
    if send_policy.mode == "allow":
        approval = "explicit_approval_for_send"
    elif send_policy.mode == "conditional":
        approval = "explicit_approval_for_send"
    elif wants_draft:
        approval = "review_before_external_action"

    if profile_context.get("company") or profile_context.get("business_name"):
        context_requirements.append("business_profile")

    # Keep the user's instruction as objective by default. Only rewrite when we have a
    # concrete target label — never "the requested market" which becomes a useless search query.
    objective = text if len(text) <= 500 else text[:497] + "..."
    if (
        "research_prospects" in outcomes
        and "prepare_outreach" in outcomes
        and send_policy.mode == "forbid"
        and entities
        and label != "the requested market"
    ):
        objective = f"Identify and prepare outreach for qualified {label} prospects without sending messages."

    # Split forbid concepts: action tokens vs display/legacy mix.
    forbidden_actions = [item for item in forbidden if "." in item and " " not in item]
    forbidden_canonical = [item for item in forbidden if item in CANONICAL_OUTCOMES]
    # Gate confidence on user-derived fields only — system defaults (e.g. qty=3)
    # must not fail ordinary research that intentionally omits quantity.
    confidences = [
        e.confidence
        for e in evidence
        if e.confidence is not None and e.source not in {"system_default", "profile_context"}
    ]
    min_conf = min(confidences) if confidences else None

    # Semantic units from clauses (coverage measured over material units).
    from backend.services.mission_composition.contracts import SemanticUnit

    semantic_units: list[SemanticUnit] = []
    unmatched_units: list[SemanticUnit] = []
    try:
        for clause in clause_models:
            unit = SemanticUnit(
                unit_id=clause.clause_id,
                kind="action" if clause.mapped_outcomes else "other",
                text=clause.text,
                accounted=clause.status == "recognized",
                mapped_outcomes=list(clause.mapped_outcomes),
                risk="high"
                if any(
                    token in clause.text.lower()
                    for token in ("delete", "charge", "invoice", "publish", "send", "overwrite")
                )
                else "low",
                reason=clause.reason,
            )
            semantic_units.append(unit)
            if clause.material and clause.status != "recognized":
                unmatched_units.append(unit)
    except Exception:
        semantic_units = []
        unmatched_units = []

    intent = MissionIntent(
        raw_instruction=raw_instruction,
        normalized_instruction=text,
        objective=objective,
        requested_outcomes=list(outcomes),
        requested_quantity=quantity,
        quantity_provenance=quantity_provenance,  # type: ignore[arg-type]
        send_policy=send_policy,
        target_entities=entities,
        constraints=constraints,
        forbidden_outcomes=forbidden,
        forbidden_actions=forbidden_actions,
        forbidden_canonical_outcomes=forbidden_canonical,
        success_criteria=success
        if success
        else [
            SuccessCriterion(
                description="Mission produces evidence-backed deliverables matching the stated objective",
                measurable=False,
            )
        ],
        urgency="normal",
        approval_preference=approval,
        budget_limits=None,
        context_requirements=context_requirements,
        ambiguity=clarifications,
        interpreted_clauses=clause_models,
        unmatched_material_clauses=unmatched,
        semantic_units=semantic_units,
        unmatched_material_units=unmatched_units,
        interpretation_evidence=evidence,
        coverage_score=round(coverage, 3),
        minimum_field_confidence=min_conf,
        components_available=list(dict.fromkeys([*components_active, "regex_core"])),
        components_executed=list(dict.fromkeys(components_active)),
        components_contributing=list(dict.fromkeys(components_active)),
        components_active=list(dict.fromkeys(components_active)),
        interpreter_version=INTERPRETER_VERSION,
    )
    from backend.services.mission_composition.readiness import evaluate_interpretation_readiness

    readiness = evaluate_interpretation_readiness(intent)
    return intent.model_copy(
        update={
            "interpretation_ready": readiness.ready,
            "interpretation_readiness_reasons": list(readiness.reasons),
            # Align ambiguity with readiness when restatement required.
            "ambiguity": clarifications
            if clarifications
            else (
                [
                    _restatement(
                        field="interpretation_readiness",
                        understood=objective[:240] if objective else None,
                        missing="; ".join(readiness.reasons)[:400],
                        include_instruction=(
                            "the full objective, target market or scope, deliverable, "
                            "and whether sending or other external actions are permitted"
                        ),
                        reason="Interpretation readiness policy failed.",
                    )
                ]
                if not readiness.ready
                else []
            ),
        }
    )
