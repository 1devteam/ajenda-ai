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
    "audit outbound operations": "verify_runtime_controls",
    "verify runtime controls": "verify_runtime_controls",
    "verify outbound controls": "verify_runtime_controls",
    "prepare an engineering review package": "verify_runtime_controls",
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
    "collect contact info": "observe_contacts",
    "collect contact details": "observe_contacts",
    "contact info": "observe_contacts",
    "contact details": "observe_contacts",
    "return the contact info": "observe_contacts",
    "return contact info": "observe_contacts",
    # Outreach
    "prepare outreach drafts": "prepare_outreach",
    "draft outreach": "prepare_outreach",
    "write introductions": "prepare_outreach",
    # CRM/GTM/vertical operator language
    "merge records": "update_crm",
    "advance opportunity": "update_crm",
    "advance the deal": "update_crm",
    "review pipeline": "update_crm",
    "segment accounts": "qualify_prospects",
    "prepare sequence": "prepare_outreach",
    "vertical research": "research_prospects",
    # Connector reads
    "check gmail": "read_email",
    "check my inbox": "read_email",
    "read my email": "read_email",
    "search my email": "read_email",
    "read hubspot": "read_crm",
    "search hubspot": "read_crm",
    "check the crm": "read_crm",
    "read crm records": "read_crm",
    "query salesforce": "query_salesforce",
    "read salesforce": "query_salesforce",
    "search salesforce": "query_salesforce",
    # Calendar read
    "check my calendar": "read_calendar",
    "calendar for": "read_calendar",
    # Operator reads (Wave A)
    "linkedin profile": "read_linkedin",
    "my linkedin profile": "read_linkedin",
    "read my linkedin": "read_linkedin",
    "check linkedin": "read_linkedin",
    "linkedin profile read": "read_linkedin",
    "github repo": "read_github",
    "github repository": "read_github",
    "read github": "read_github",
    "check github": "read_github",
    "read github repo": "read_github",
    "google contacts": "read_contacts",
    "my google contacts": "read_contacts",
    "read my contacts": "read_contacts",
    "list my contacts": "read_contacts",
    "check my contacts": "read_contacts",
    "read google contacts": "read_contacts",
}

# Regex patterns that map a clause/window to a canonical outcome (deterministic).
OUTCOME_PHRASE_PATTERNS: tuple[tuple[str, CanonicalOutcome], ...] = (
    (r"\b(?:audit|verify|review)\b.{0,80}\b(?:outbound|egress|runtime)\b", "verify_runtime_controls"),
    (r"\breview\s+my\s+business\b.{0,120}\b(?:increase|grow|improve)\s+(?:my\s+)?income\b", "review_business_income"),
    (r"\b(?:increase|grow|improve)\s+(?:my\s+)?income\b.{0,80}\bmy\s+business\b", "review_business_income"),
    (r"\b(?:prepare|create|produce)\b[^.!?]{0,48}\binvoice\s+drafts?\b", "prepare_invoice_drafts"),
    (r"\b(?:read|check|show|list|fetch)\b[^.!?]{0,48}\b(?:stripe|revenue|invoices?)\b", "read_revenue"),
    (r"\b(?:prepare|create|produce)\b[^.!?]{0,48}\b(?:revenue\s+)?reconciliation\b", "prepare_reconciliation"),
    (r"\b(?:check|read|search|list|show)\b.{0,48}\b(?:gmail|inbox)\b", "read_email"),
    (r"\b(?:gmail|inbox)\b.{0,48}\b(?:unread|recent|replies?|messages?|emails?)\b", "read_email"),
    (r"\b(?:check|read|search|list|show)\s+my\s+(?:emails?|messages?)\b", "read_email"),
    (r"\b(?:check|read|search|query|list|show)\b[^.!?]{0,48}\b(?:hubspot|crm)\b", "read_crm"),
    (
        r"\b(?:read|check|search|query|list|show|summarize|find|look up)\b[^.!?]{0,48}\b(?:hubspot|crm)\b[^.!?]{0,48}\b(?:records?|contacts?|companies|deals?|pipeline)\b",
        "read_crm",
    ),
    (r"\b(?:query|check|read|search|list|show)\b.{0,48}\bsalesforce\b", "query_salesforce"),
    (r"\bsalesforce\b.{0,48}\b(?:accounts?|contacts?|leads?|opportunities|records?|pipeline)\b", "query_salesforce"),
    (r"\bqualify\b", "qualify_prospects"),
    (
        r"\bscore(?:s|d|ing)?\s+(?:them|these|those|it|the\s+(?:prospects?|leads?|competitors?))\b",
        "qualify_prospects",
    ),
    (
        r"\brank(?:s|ed|ing)?\s+(?:them|these|those|the\s+(?:strongest|best|prospects?|leads?|competitors?))\b",
        "qualify_prospects",
    ),
    (
        r"\brate(?:s|d|ing)?\s+(?:them|these|those|the\s+(?:prospects?|leads?|competitors?))\b",
        "qualify_prospects",
    ),
    (
        r"\bgrade(?:s|d|ing)?\s+(?:them|these|those|the\s+(?:prospects?|leads?|competitors?))\b",
        "qualify_prospects",
    ),
    (r"\bstrong(?:est)? prospects?\b", "qualify_prospects"),
    (r"\bbest (?:leads?|prospects?)\b", "qualify_prospects"),
    (r"\bbest\b[^.!?]{0,40}\b(?:companies|businesses|services|options)\b", "qualify_prospects"),
    (r"\btop (?:leads?|prospects?)\b", "qualify_prospects"),
    (r"\btop (?:three|five)\b", "qualify_prospects"),
    (r"\bpick the (?:strongest|best)\b", "qualify_prospects"),
    (r"\bidentify .* (?:strong|best|top)\b", "qualify_prospects"),
    (
        r"\b(?:collect|return|gather|get)\b.{0,32}\bcontact (?:info|information|details)\b",
        "observe_contacts",
    ),
    (r"\bcontact (?:info|information|details)\b", "observe_contacts"),
    (r"\b(?:emails?|phone numbers?)\s+for\b", "observe_contacts"),
    # Wave A operator reads — read intent only (not publish / CRM write).
    (r"\b(?:check|read|show|fetch|get)\b.{0,40}\blinkedin\b.{0,24}\bprofile\b", "read_linkedin"),
    (r"\blinkedin\b.{0,24}\bprofile\b", "read_linkedin"),
    (r"\b(?:my|the)\s+linkedin\s+profile\b", "read_linkedin"),
    (r"\b(?:check|read|show|fetch|get)\b.{0,40}\bgithub\b.{0,32}\b(?:repo|repository)\b", "read_github"),
    (r"\bgithub\b.{0,24}\b(?:repo|repository)\b", "read_github"),
    (r"\b(?:check|read|list|show|fetch)\b.{0,40}\b(?:google\s+)?contacts?\b", "read_contacts"),
    (r"\b(?:my|the)\s+(?:google\s+)?contacts?\b", "read_contacts"),
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
