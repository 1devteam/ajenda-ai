"""Structured lexical classification used alongside the deterministic interpreter.

This is an additive bridge away from unbounded regex growth. It classifies
language into bounded verb/source/entity/operation dimensions; it proposes no
outcomes, abilities, credentials, or runtime work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

LexicalVerb = Literal["read", "discover", "qualify", "write", "send", "unknown"]
LexicalSource = Literal["internal_crm", "hubspot", "salesforce", "public", "unknown"]
LexicalEntity = Literal["records", "prospects", "contacts", "pipeline", "unknown"]
LexicalOperation = Literal["read", "research", "mutation", "unknown"]


@dataclass(frozen=True, slots=True)
class LexicalFrame:
    """Bounded interpretation facts; all fields are non-authoritative."""

    verb: LexicalVerb = "unknown"
    source: LexicalSource = "unknown"
    entity: LexicalEntity = "unknown"
    operation: LexicalOperation = "unknown"
    internal_crm_read: bool = False


_READ = re.compile(r"\b(?:read|check|list|show|query|review|inspect|summari[sz]e|compare|rank)\b", re.I)
_DISCOVER = re.compile(r"\b(?:research|discover|find|search)\b", re.I)
_QUALIFY = re.compile(r"\b(?:qualify|score|rank|rate|grade)\b", re.I)
_WRITE = re.compile(r"\b(?:create|update|mutate|write|delete|remove|change)\b", re.I)
_SEND = re.compile(r"\b(?:send|deliver|dispatch|publish)\b", re.I)
_INTERNAL_CRM = re.compile(
    r"\b(?:ajenda(?:['\u2019]s)?\s+)?internal\s+(?:ajenda\s+)?crm\b|\bajenda(?:['\u2019]s)?\s+crm\b", re.I
)
_HUBSPOT = re.compile(r"\bhubspot\b", re.I)
_SALESFORCE = re.compile(r"\bsalesforce\b", re.I)
_PROSPECTS = re.compile(r"\b(?:prospects?|leads?|companies)\b", re.I)
_CONTACTS = re.compile(r"\bcontacts?\b", re.I)
_PIPELINE = re.compile(r"\b(?:pipeline|deals?|opportunities)\b", re.I)
_RECORDS = re.compile(r"\brecords?\b", re.I)


def classify_lexical_frame(text: str) -> LexicalFrame:
    """Classify bounded lexical dimensions without selecting a runtime path."""

    source: LexicalSource = "unknown"
    if _INTERNAL_CRM.search(text):
        source = "internal_crm"
    elif _HUBSPOT.search(text):
        source = "hubspot"
    elif _SALESFORCE.search(text):
        source = "salesforce"
    elif re.search(r"\b(?:public|web|website|internet|online)\b", text, re.I):
        source = "public"

    verb: LexicalVerb = "unknown"
    if _SEND.search(text):
        verb = "send"
    elif _WRITE.search(text):
        verb = "write"
    elif _QUALIFY.search(text):
        verb = "qualify"
    elif _DISCOVER.search(text):
        verb = "discover"
    elif _READ.search(text):
        verb = "read"

    entity: LexicalEntity = "unknown"
    if _PIPELINE.search(text):
        entity = "pipeline"
    elif _CONTACTS.search(text):
        entity = "contacts"
    elif _PROSPECTS.search(text):
        entity = "prospects"
    elif _RECORDS.search(text):
        entity = "records"

    operation: LexicalOperation = "unknown"
    if verb in {"write", "send"}:
        operation = "mutation"
    elif verb in {"discover", "qualify"}:
        operation = "research"
    elif verb == "read":
        operation = "read"

    return LexicalFrame(
        verb=verb,
        source=source,
        entity=entity,
        operation=operation,
        internal_crm_read=source == "internal_crm" and operation == "read",
    )
