"""Deterministic lexical rule engine for mission intent interpretation.

Owns regex vocabulary, clause segmentation/classification, target extraction,
clarification/evidence helpers, and success-criteria construction. It has no
mission execution, credential, queue, or side-effect authority.
"""

from __future__ import annotations

import re

from backend.services.mission_composition.ability_vocab import phrase_maps_to_outcome
from backend.services.mission_composition.contracts import (
    INTERPRETER_VERSION,
    CanonicalOutcome,
    Clarification,
    InterpretationEvidence,
    SuccessCriterion,
    TargetEntity,
)
from backend.services.mission_composition.deliverable_contract import extract_deliverable_request

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
    r"nothing should be sent",
    r"\b(?:forbid|forbids|forbidden|prohibit|prohibits|prohibited)\b[^.!?]{0,80}\bsend(?:ing)?\b",
    # Covers coordinated prohibitions such as “Do not browse, contact anyone,
    # send email, or perform any external action.” Clause splitting must not
    # turn the later list items into authorized actions.
    r"\b(?:do not|don't|dont|never)\b[^.!?]{0,180}\bsend(?:ing)?\b",
)
_CONDITIONAL_SEND_PATTERNS = (
    r"send only after",
    r"after (?:i |my )?approv",
    r"once (?:i |you )?approv",
    r"until (?:i |you )?approv",
    r"hold until",
    r"nothing goes out without",
)
_SEND_CONTRADICTION_PATTERNS = (
    r"\bsend\b[^.;]{0,64}\b(?:but|however)\b[^.;]{0,32}\b(?:do not|don't|dont|never)\s+send\b",
    r"\b(?:do not|don't|dont|never)\s+send\b[^.;]{0,64}\b(?:but|however)\b[^.;]{0,32}\bsend\b",
    r"\bsend(?:ing)?\b[^.!?]{0,160}[.!?][^.!?]{0,80}\b(?:do not|don't|dont|never)\s+send\b",
    r"\b(?:do not|don't|dont|never)\s+send\b[^.!?]{0,160}[.!?][^.!?]{0,80}\bsend(?:ing)?\b",
)
_DRAFT_PATTERNS = (
    r"\bdraft\b",
    r"\bdrafts\b",
    r"introduction",
    r"outreach",
    r"personalized",
)
_QUALIFY_PATTERNS = (
    r"\bqualify\b",
    r"strong prospects",
    r"identify .* prospects",
    r"best (?:leads|prospects)",
    r"\bbest\b[^.!?]{0,40}\b(?:companies|businesses|services|options)\b",
    # Score/rank/rate only when aimed at prospects/leads/competitors (not reports/rates).
    r"\bscore(?:s|d|ing)?\s+(?:them|these|those|it|the\s+(?:prospects?|leads?|competitors?))\b",
    r"\bscore(?:s|d|ing)?\s+the\b[^.!?]{0,60}\b(?:prospects?|leads?|competitors?)\b",
    r"\brank(?:s|ed|ing)?\s+(?:them|these|those|the\s+(?:strongest|best|prospects?|leads?|competitors?))\b",
    r"\brank(?:s|ed|ing)?\s+the\b[^.!?]{0,60}\b(?:prospects?|leads?|competitors?)\b",
    r"\brank(?:s|ed|ing)?\b[^.!?]{0,80}\b(?:companies|accounts?|records?)\b",
    r"\brate(?:s|d|ing)?\s+(?:them|these|those|the\s+(?:prospects?|leads?|competitors?))\b",
    r"\brate(?:s|d|ing)?\s+the\b[^.!?]{0,60}\b(?:prospects?|leads?|competitors?)\b",
    r"\bgrade(?:s|d|ing)?\s+(?:them|these|those|the\s+(?:prospects?|leads?|competitors?))\b",
    r"\bgrade(?:s|d|ing)?\s+the\b[^.!?]{0,60}\b(?:prospects?|leads?|competitors?)\b",
    r"\btop (?:leads?|prospects?)\b",
    r"\btop (?:three|five)\b",
    r"\bstrongest (?:leads?|prospects?|competitors?)\b",
    r"\bpick the (?:strongest|best)\b",
    r"\bchoose (?:the )?(?:strongest|best)(?:\s+\w+)?\b",
)
_RESEARCH_PATTERNS = (
    r"\bresearch\b",
    r"\bresearch\b[^.!?]{0,120}\b(?:ajenda\s+)?internal\s+crm\s+records?\b",
    r"\bfind\b",
    r"\bdiscover\b",
    r"companies in",
    r"prospects",
    r"competitors?",
    r"competors?",
)
# A direct record-read request must not be mistaken for market discovery merely
# because the records are scoped to prospects or a market.  Source-qualified
# research ("research ... from CRM") remains distinct and is handled below.
_DIRECT_CRM_RECORD_READ = re.compile(
    r"\b(?:read|review|inspect|list|query|summari[sz]e)\b"
    r"[^.!?]{0,80}\b(?:approved\s+)?(?:hubspot\s+)?crm\s+records?\b",
    re.IGNORECASE,
)
_LOCATION_TRAILING_STOP = re.compile(
    r"\s+\b(?:"
    r"identify|find|discover|and|with|for|to|that|who|which|"
    r"strong|best|top|draft|enrich|qualify|send|prepare|score|rank|"
    r"prospects?|competitors?|competors?|leads?|using|from|against|return|produce|provide|"
    r"scores?|reasons?"
    r")\b",
    re.IGNORECASE,
)
_ENRICH_PATTERNS = (
    r"\benrich(?:es|ed|ing|ment)?\b",
    r"\benrich (?:the )?(?:leads?|contacts?|prospects?)\b",
)
_OBSERVE_CONTACT_PATTERNS = (
    r"observe (?:public )?contact evidence",
    r"contact details",
    r"contact info(?:rmation)?",
    r"collect (?:contact|email|phone)",
    r"gather (?:contact|email|phone)",
    r"return (?:the )?(?:contact|email|phone)",
    r"find (?:emails?|phone numbers?)",
    r"look up (?:emails?|phone numbers?|contact info)",
)
_EMAIL_READ_PATTERNS = (
    # Require Gmail/inbox context — bare "email/message" often means CRM fields.
    r"\b(?:check|read|search|list|show)\b.{0,48}\b(?:gmail|inbox)\b",
    r"\b(?:gmail|inbox)\b.{0,48}\b(?:unread|recent|replies?|messages?|emails?)\b",
    r"\b(?:check|read|search|list|show)\s+my\s+(?:emails?|messages?)\b",
)
_CRM_READ_PATTERNS = (
    r"\b(?:check|read|search|query|list|show|summarize|find|look up)\b[^.!?]{0,48}\b(?:hubspot|crm)\b",
    r"\b(?:hubspot|crm)\b[^.!?]{0,48}\b(?:records?|contacts?|companies|deals?|pipeline)\b",
)
_INTERNAL_CRM_READ_PATTERNS = (
    # Internal CRM review is a local record read. Keep it distinct from
    # connector reads so Ajenda does not route it through HubSpot research.
    r"\b(?:review|inspect|summarize|compare|rank)\b[^.!?]{0,120}\b(?:ajenda(?:['\u2019]s)?\s+crm|ajenda\s+internal\s+crm|internal\s+(?:ajenda\s+)?crm)\b",
    r"\b(?:ajenda(?:['\u2019]s)?\s+crm|ajenda\s+internal\s+crm|internal\s+(?:ajenda\s+)?crm)\b[^.!?]{0,100}\b(?:records?|companies|contacts?|deals?|pipeline)\b",
    r"\b(?:review|inspect|summarize|compare|rank)\b[^.!?]{0,120}\b(?:ajenda(?:['\u2019]s)?\s+internal\s+records?|internal\s+records?)\b",
    r"\b(?:find|search|research|identify|qualify)\b[^.!?]{0,120}\bfrom\s+(?:the\s+)?internal\s+(?:ajenda\s+)?crm\b",
    # Natural read requests may lead with "read", "check", or "list" and
    # use the internal CRM as a source qualifier. Keep this a read outcome;
    # it must never imply a CRM write or provider call.
    r"\b(?:read|check|list|show|query|review|inspect|summarize|compare|rank)\b[^.!?]{0,120}\bfrom\s+(?:the\s+)?(?:ajenda\s+)?internal\s+crm\b",
    r"\b(?:read|check|list|show|query|review|inspect|summarize|compare|rank)\b[^.!?]{0,120}\bfrom\s+(?:the\s+)?internal\s+(?:ajenda\s+)?crm\b",
)
_CRM_READ_NEGATION_PATTERNS = (
    r"\b(?:do not|don't|dont|never|without)\b[^.!?]{0,48}\b(?:read|check|search|query|list|show)\b[^.!?]{0,48}\b(?:hubspot|crm)\b",
    r"\b(?:do not|don't|dont|never|without)\b[^.!?]{0,48}\b(?:hubspot|crm)\b[^.!?]{0,48}\b(?:read|check|search|query|list|show)\b",
)
_INTERNAL_CRM_READ_NEGATION_PATTERNS = (
    r"\b(?:do not|don't|dont|never|without)\b[^.!?]{0,80}\b(?:read|review|inspect|summarize|compare|rank)\b[^.!?]{0,80}\b(?:ajenda(?:['\u2019]s)?\s+(?:internal\s+)?crm|internal\s+(?:ajenda\s+)?crm|internal\s+records?)\b",
)
_CRM_READBACK_VERIFICATION_PATTERN = re.compile(
    r"\bread\s+back\b[^.!?]{0,80}\b(?:saved|persisted)\s+(?:crm\s+)?records?\b",
    re.IGNORECASE,
)
_SALESFORCE_QUERY_PATTERNS = (
    r"\b(?:query|check|read|search|list|show|summarize)\b.{0,48}\bsalesforce\b",
    r"\bsalesforce\b.{0,48}\b(?:accounts?|contacts?|leads?|opportunities|records?|pipeline)\b",
)

# Wave A operator reads — distinct from publish (LinkedIn) and CRM write (contacts).
_LINKEDIN_READ_PATTERNS = (
    r"\b(?:check|read|show|fetch|get|open)\b.{0,40}\blinkedin\b.{0,24}\bprofile\b",
    r"\blinkedin\b.{0,24}\bprofile\b",
    r"\b(?:my|the)\s+linkedin\s+profile\b",
    r"\bread\s+(?:my\s+)?linkedin\b",
)
_GITHUB_READ_PATTERNS = (
    r"\b(?:check|read|show|fetch|get|open)\b.{0,40}\bgithub\b.{0,40}\b(?:repo|repository)\b",
    r"\bgithub\b.{0,24}\b(?:repo|repository)\b",
    r"\bread\s+(?:the\s+)?github\b",
    r"\bgithub\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\b",
)
_CONTACTS_READ_PATTERNS = (
    r"\b(?:check|read|list|show|fetch|get)\b.{0,40}\bgoogle\s+contacts\b",
    r"\bgoogle\s+contacts\b",
    r"\b(?:check|read|list|show)\b.{0,24}\b(?:my\s+)?contacts\b",
    r"\b(?:my|the)\s+(?:google\s+)?contacts\b",
)

_HUBSPOT_COMPANY_AFTER = re.compile(
    r"\b(?:hubspot|(?:the\s+)?crm)\s+(?:for|about|on|matching)\s+"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9.&'\-/]*(?:\s+[A-Za-z0-9][A-Za-z0-9.&'\-/]*){0,5}?)"
    r"(?=$|[,;.]|\s+\band\b|\s+\bthen\b)",
    re.IGNORECASE,
)
_HUBSPOT_COMPANY_BEFORE = re.compile(
    r"\b(?:find|search|check|read|look\s+up|show)\s+"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9.&'\-/]*(?:\s+[A-Za-z0-9][A-Za-z0-9.&'\-/]*){0,5})"
    r"\s+(?:in|on|from)\s+(?:hubspot|(?:the\s+)?crm)\b",
    re.IGNORECASE,
)
_HUBSPOT_COMPANY_RECORD_FOR = re.compile(
    r"\b(?:crm\s+)?records?\s+(?:for|about|on)\s+"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9.&'\-/]*(?:\s+[A-Za-z0-9][A-Za-z0-9.&'\-/]*){0,5}?)"
    r"(?=$|[,;.]|\s+\band\b|\s+\bthen\b)",
    re.IGNORECASE,
)
_HUBSPOT_COMPANY_NAMED = re.compile(
    r"\b(?:company|account|record)\s+(?:named|called)\s+"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9.&'\-/]*(?:\s+[A-Za-z0-9][A-Za-z0-9.&'\-/]*){0,5}?)"
    r"(?=$|[,;.?!]|\s+\b(?:from|in|on|and|then)\b)",
    re.IGNORECASE,
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
    r"\bpersist (?:them|it|these|those|each|the\s+(?:prospects?|leads?|companies))?\s*(?:to|into|in)\s+(?:the\s+)?(?:ajenda\s+)?(?:internal\s+)?crm\b",
    r"\bpersist\s+(?:only\s+)?(?:approved\s+)?(?:the\s+)?(?:prospects?|leads?|companies|records?)\s+(?:to|into|in)\s+(?:the\s+)?(?:ajenda\s+)?(?:internal\s+)?crm\b",
    r"\bupdate (?:the )?(?:crm|pipeline|hubspot)\b",
    r"\blog (?:to |in |into )?(?:the )?crm\b",
    r"\blogs? (?:activity|to crm)\b",
    r"\bupsert\b",
    r"\bwrite (?:to |into )?(?:the )?crm\b",
    r"\bsync (?:to |into )?(?:the )?(?:crm|hubspot|contacts?)\b",
    r"\bpush (?:to |into )?(?:the )?(?:crm|hubspot|contacts?)\b",
    r"\badd (?:them|it|these|those|each|leads?|prospects?|companies)?\s*(?:to|into)\s+(?:my\s+)?(?:crm\s+)?contacts?\b",
    r"\bsave (?:them|it|these|those|each|leads?|prospects?)?\s*(?:to|into|in)\s+(?:my\s+)?(?:crm\s+)?contacts?\b",
    r"\bsave\s+(?:each|the)?\s*(?:company|companies|account|accounts)\b",
    r"\bsave\s+(?:only\s+)?(?:approved\s+)?(?:the\s+)?(?:prospects?|leads?|companies|records?)\s+(?:to|into|in)\s+(?:the\s+)?(?:ajenda\s+)?(?:internal\s+)?crm\b",
    # Explicit CRM record batches. These phrases commonly enumerate the
    # records to create/update before naming the internal CRM as the system
    # of record (for example, "persist the following contacts to Ajenda
    # internal CRM" or "create/update account, contact, and deal records").
    r"\b(?:persist|save|write|upsert|create|update)\b[^.!?]{0,140}\b(?:account|accounts|company|companies|contact|contacts|deal|deals|opportunit(?:y|ies)|record|records)\b[^.!?]{0,100}\b(?:ajenda\s+)?(?:internal\s+)?crm\b",
    r"\b(?:create|update|save|persist|write|upsert)\b[^.!?]{0,120}\b(?:account|accounts|company|companies|contact|contacts|deal|deals|opportunit(?:y|ies)|record|records)\b",
    r"\badd (?:them|it|these|those)\s+to\s+(?:the\s+)?(?:crm|hubspot|pipeline)\b",
    r"\bsave (?:them|it|these|those)\s+to\s+(?:the\s+)?(?:crm|hubspot|pipeline)\b",
    # Natural "save / add to contacts" language (Google Contacts, CRM, or internal contact book).
    r"\bput (?:them|it|these|those)\s+(?:in|into)\s+(?:my\s+)?(?:crm\s+)?contacts?\b",
    r"\bcreate (?:crm )?(?:records?|contacts?)\b",
    r"\b(?:create|add)\s+(?:a\s+)?(?:deal|opportunit(?:y|ies))(?:\s+record)?\b",
    r"\bopen\s+(?:a\s+)?(?:new|fresh)\s+(?:deal|opportunit(?:y|ies))(?:\s+record)?\b",
    r"\b(?:create|link|assign)\s+(?:a\s+)?(?:deal|opportunit(?:y|ies))\b",
    r"\b(?:modify|change|edit) (?:the )?(?:crm|hubspot|pipeline|records?)\b",
)
_INTERNAL_CRM_PATTERNS = (
    r"\bajenda(?:'s)?\s+(?:internal\s+)?crm\b",
    r"\binternal\s+(?:ajenda\s+)?crm\b",
    r"\bajenda\s+(?:internal\s+)?records?\b",
)
_CRM_NEGATION_PATTERNS = (
    r"\b(?:do not|don't|dont|never|without)\s+add\b.{0,40}\bcontacts?\b",
    r"\b(?:do not|don't|dont|never|without)\s+save\b.{0,40}\bcontacts?\b",
    r"\b(?:do not|don't|dont|never|without)\s+(?:add|save|sync|push|write|update|log|upsert|create)\b.{0,48}\b(?:crm|hubspot|pipeline|contacts?)\b",
    r"\bno\s+(?:crm|contact)\s+(?:updates?|writes?|saves?)\b",
    r"\bwithout\s+(?:adding|saving)\s+(?:them\s+)?to\s+contacts?\b",
    r"\b(?:do not|don't|dont|never|without)\b[^.;]{0,96}\b(?:update|write|sync|push|log|upsert|create)\b[^.;]{0,32}\b(?:crm|hubspot|pipeline|contacts?)\b",
    r"\b(?:do not|don't|dont|never)\b[^.!?]{0,180}\b(?:modify|change|edit)\b[^.!?]{0,32}\b(?:crm|hubspot|pipeline|records?)\b",
)
_NO_EXTERNAL_ACTION_PATTERNS = (
    r"\b(?:do not|don't|dont|never)\b[^.!?]{0,180}\b(?:contact|send|modify|perform)\b",
    r"\bwithout\b[^.!?]{0,180}\b(?:contact|send|modify|perform)\b",
)
_PROMPT_INJECTION_PATTERNS = (
    r"\b(?:treat|consider|regard)\b[^.!?]{0,180}\b(?:untrusted|not authority|not instructions?)\b",
)
_BUSINESS_PROFILE_READ_PATTERNS = (
    r"\b(?:search|read|retrieve|look up|find|summarize)\b[^.!?]{0,72}\b(?:approved )?business profile\b",
    r"\b(?:search|read|retrieve|look up|find|summarize)\b[^.!?]{0,72}\bgoverned internal memory\b",
    r"\b(?:company facts|who (?:is|are) ajenda|ajenda(?:'s|s) products and services)\b",
)
# A profile used as mission context is not itself a profile-read deliverable.
# Keep this clause recognized so composition does not silently drop the
# operator's declared company/product authority.
_BUSINESS_PROFILE_CONTEXT_PATTERNS = (
    r"\buse\s+(?:the\s+)?(?:approved\s+)?(?:business|company)\s+profile\b",
    r"\b(?:company|business)\s+profile\s+(?:for|of)\s+[A-Za-z0-9][^.;!?]{0,80}",
    # Product knowledge is an approved business-profile fact. Treat requests
    # to use it as context for an existing mission, never as a new authority-
    # bearing outcome or executable capability.
    r"\b(?:use|with|from)\b[^.!?]{0,100}\b(?:approved|canonical)\b[^.!?]{0,80}\bproduct\s+(?:catalog|knowledge|capabilities?)\b",
    r"\b(?:approved|canonical)\s+(?:crm|gtm)\s+product\s+knowledge\b",
)
_BUSINESS_PROFILE_DELIVERABLE_PATTERNS = (
    r"\bproducts?\b",
    r"\bservices?\b",
    r"\btarget customers?\b",
    r"\bdifferentiators?\b",
    r"\bcompany brief\b",
    r"\bevidence[- ]backed brief\b",
    r"\bmissing or conflicting (?:facts|information)\b",
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
    r"\b(?:do not|don't|dont|never|without)\b[^.;]{0,64}\b(?:publish|post|share)\b",
)
# Publish that must wait on upstream research outputs (not standalone copy).
_PUBLISH_RESULT_BASED = re.compile(
    r"\b(?:post|publish|share)\s+(?:the\s+)?(?:results?|findings?|them)\b",
    re.IGNORECASE,
)
_COUNT_PATTERN = re.compile(r"\b(\d+|one|three|two|four|five|ten)\b", re.IGNORECASE)
_WORD_COUNTS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "ten": 10,
}

_QUALIFICATION_COUNT_PATTERN = re.compile(
    r"\b(?:qualif(?:y|ied|ication)|strongest|top|best|pick|choose|select)\b"
    r"[^.!?]{0,40}?(\d+|three|two|four|five|ten)\b",
    re.IGNORECASE,
)
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
    r"(?=$|[\s,;.:]|\band\b|\bcomparable\s+to\b)",
    re.IGNORECASE,
)
_SOFTWARE_RND_LOCATION = re.compile(
    r"\b(?P<industry>software\s+and\s+r&d\s+developer)\s+companies\s+in\s+"
    r"(?P<location>[A-Za-z][A-Za-z.\-]{1,40}(?:\s+[A-Za-z][A-Za-z.\-]{1,40}){0,3})"
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
        "qualify",
        "score",
        "rank",
        "rate",
        "grade",
        "search",
        "locate",
        "analyze",
        "study",
        "review",
        "target",
        "but",
        "only",
        "return",
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
_CLAUSE_ACTION_START = (
    r"(?:do not|don't|dont|never|research|find|discover|identify|qualify|score|rank|rate|grade|draft|prepare|"
    r"send|deliver|dispatch|mail|enrich|collect|gather|return|produce|provide|check|read|search|query|list|show|summarize|"
    r"look up|schedule|book|create|add|delete|cancel|reschedule|update|remove|move|log|upsert|write|sync|push|"
    r"save|put|publish|post|share|browse|contact|perform|approve|charge|invoice|fax|wire|transfer|pay|refund|terminate)\b"
)
_CLAUSE_SPLIT = re.compile(
    rf"\s*(?:(?:,|;)\s*(?:and\s+)?|\band\b\s*)(?={_CLAUSE_ACTION_START})",
    re.IGNORECASE,
)
_CLAUSE_SENTENCE_SPLIT = re.compile(
    rf"(?<=[.!?])\s+(?={_CLAUSE_ACTION_START})",
    re.IGNORECASE,
)
_COORDINATED_PROHIBITION_START = re.compile(
    r"^(?:do not|don't|dont|never)\b",
    re.IGNORECASE,
)
_DETAILED_RETURN_DELIVERABLE = re.compile(
    r"^(?:return|produce|provide|create)\b.*(?:sourced\s+comparison|comparison\s+table|report\b|highlight\b|evidence\s+gaps?)",
    re.IGNORECASE,
)
_REPORT_SYNTHESIS_CLAUSE = re.compile(
    r"^(?:(?:return|produce|provide|create)\b.*(?:sourced\s+comparison|comparison\s+table|report\b)|"
    r"highlight\b.*opportunit|identify\b.*evidence\s+gaps?)",
    re.IGNORECASE,
)
_REPORT_SYNTHESIS_REQUEST = re.compile(
    # Evidence-gap language is a field request for many typed artifacts
    # (identity, goal evaluation, business review). It only implies research
    # synthesis when paired with an explicit research-report/comparison intent.
    r"\b(?:sourced\s+comparison|comparison\s+(?:table|report)|research\s+report|"
    r"(?:return|produce|provide|create)\b[^.!?]{0,120}\breport\b|highlight\b.*opportunit)",
    re.IGNORECASE,
)
_BUSINESS_REVIEW_CLAUSE = re.compile(
    r"^(?:use\s+only\s+the\s+approved\s+business\s+profile|"
    r"identify\b.*\b(?:income|revenue|opportunit)|"
    r"list\b.*\bevidence\s+gaps?)",
    re.IGNORECASE,
)
_EXPLICIT_WEB_URL = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _contains_unnegated_send(text: str) -> bool:
    """Detect a send verb whose sentence is not governed by a send prohibition."""

    for match in re.finditer(r"\b(?:send|sending|deliver|dispatch|mail)\b", text, flags=re.IGNORECASE):
        sentence_start = max(text.rfind(token, 0, match.start()) for token in ".!?\n")
        sentence = text[sentence_start + 1 : match.start()]
        sentence_end = min(
            [index for index in (text.find(token, match.end()) for token in ".!?\n") if index >= 0] or [len(text)]
        )
        full_sentence = text[sentence_start + 1 : sentence_end]
        if _contains_any(full_sentence, _PROMPT_INJECTION_PATTERNS):
            continue
        if re.search(
            r"\b(?:do not|don't|dont|never|without|forbid|forbids|forbidden|prohibit|prohibits|prohibited)\b",
            sentence,
            flags=re.IGNORECASE,
        ):
            continue
        return True
    return False


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


def _extract_qualification_count(text: str) -> int | None:
    """Extract the requested count for a qualification/ranking stage."""

    match = _QUALIFICATION_COUNT_PATTERN.search(_DATE_SPAN.sub(" ", text))
    if match is None:
        return None
    raw = match.group(1).lower()
    value = int(raw) if raw.isdigit() else _WORD_COUNTS.get(raw)
    return value if value is not None and 1 <= value <= 50 else None


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


def _extract_industry_location_entities(text: str) -> list[TargetEntity]:
    matches = list(_SOFTWARE_RND_LOCATION.finditer(text)) + list(_INDUSTRY_LOCATION.finditer(text))
    matches.sort(key=lambda item: item.start())
    entities: list[TargetEntity] = []
    for match in matches:
        industry_tokens = [token for token in match.group("industry").strip().split() if token]
        while industry_tokens and industry_tokens[0].lower() in _LEADING_VERB_WORDS:
            industry_tokens.pop(0)
        while industry_tokens and (
            industry_tokens[0].lower() in _LEADING_QUANTITY_WORDS or industry_tokens[0].isdigit()
        ):
            industry_tokens.pop(0)
        industry = " ".join(industry_tokens).strip(" ,.;:")
        location = _trim_location(match.group("location"))
        # Drop trailing source qualifiers ("from HubSpot CRM records").
        location = re.sub(r"\s+\bfrom\b\s+.*$", "", location, flags=re.IGNORECASE).strip(" ,.;:")
        if not industry or not location:
            continue
        if not any(
            entity.industry
            and entity.location
            and entity.industry.casefold() == industry.casefold()
            and entity.location.casefold() == location.casefold()
            for entity in entities
        ):
            entities.append(
                TargetEntity(
                    type="company",
                    industry=industry,
                    location=location,
                    provenance="explicit",
                    confidence=0.95,
                )
            )
    return entities


def _extract_target_entities(text: str) -> list[TargetEntity]:
    """Retain explicit research / connector targets (competitors, market, CRM company)."""

    entities: list[TargetEntity] = []
    # A browser observation is only executable when its URL becomes typed
    # intent data.  Keep the URL as a web_page entity so the resolver can
    # provide target_url without scraping the raw instruction downstream.
    url_match = _EXPLICIT_WEB_URL.search(text)
    if url_match is not None:
        url = url_match.group(0).rstrip(".,;:!?)]}")
        entities.append(
            TargetEntity(
                type="web_page",
                url=url,
                provenance="explicit",
                confidence=0.99,
            )
        )
    entities.extend(_extract_competitors_of(text))
    entities.extend(_extract_industry_location_entities(text))
    # Connector company targets (HubSpot for Acme) — only when no market target already.
    if not entities:
        entities.extend(_extract_connector_company(text))
    return entities


def _extract_connector_company(text: str) -> list[TargetEntity]:
    """Extract an explicit company target for a HubSpot/CRM read."""

    match = (
        _HUBSPOT_COMPANY_AFTER.search(text)
        or _HUBSPOT_COMPANY_BEFORE.search(text)
        or _HUBSPOT_COMPANY_RECORD_FOR.search(text)
        or _HUBSPOT_COMPANY_NAMED.search(text)
    )
    if match is None:
        return []
    name = match.group("name").strip(" ,.;:")
    if not name or name.lower() in {"records", "contacts", "companies", "deals", "pipeline"}:
        return []
    return [
        TargetEntity(
            type="company",
            name=name,
            attributes={"connector": "hubspot", "research_mode": "crm_read"},
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
        _RESEARCH_PATTERNS
        + _DRAFT_PATTERNS
        + _SEND_PATTERNS
        + _QUALIFY_PATTERNS
        + _CALENDAR_PATTERNS
        + _EMAIL_READ_PATTERNS
        + _CRM_READ_PATTERNS
        + _SALESFORCE_QUERY_PATTERNS,
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
    if "synthesize_research_report" in outcomes:
        success.append(
            SuccessCriterion(
                description="A research_report artifact compares the observed candidates and identifies evidence gaps",
                measurable=True,
            )
        )
    if "review_business_income" in outcomes:
        success.append(
            SuccessCriterion(
                description="A business_review_report lists evidence-backed income opportunities, assumptions, and evidence gaps",
                measurable=True,
            )
        )
    if "evaluate_goal_progress" in outcomes:
        success.append(
            SuccessCriterion(
                description="A goal_progress_evaluation artifact reports status, confidence, KPI gaps, and evidence gaps",
                measurable=True,
            )
        )
    if "verify_runtime_controls" in outcomes:
        success.append(
            SuccessCriterion(
                description="A runtime_control_verification_package classifies each requested control and includes redacted local evidence",
                measurable=True,
            )
        )
    if "observe_contacts" in outcomes:
        success.append(
            SuccessCriterion(
                description=f"{n} prospects include observed phone or email from a fetched page",
                measurable=True,
            )
        )
    if "observe_web_page" in outcomes:
        success.append(
            SuccessCriterion(
                description=(
                    "A web_page_observation artifact records the requested URL, final URL, title, visible body text, "
                    "and browser step evidence with satisfied observation requirements"
                ),
                measurable=True,
            )
        )
    if "verify_public_identity" in outcomes:
        success.append(
            SuccessCriterion(
                description=(
                    "A public_identity_observation artifact records the expected company, industry, location, "
                    "identity status, and source-backed evidence or explicit gaps"
                ),
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
    if "read_revenue" in outcomes:
        success.append(
            SuccessCriterion(
                description="Settled Stripe revenue records are returned with verified webhook evidence",
                measurable=True,
            )
        )
    if "prepare_reconciliation" in outcomes:
        success.append(
            SuccessCriterion(
                description="A reconciliation package reports settled record count, totals, and currencies",
                measurable=True,
            )
        )
    if "prepare_invoice_drafts" in outcomes:
        success.append(
            SuccessCriterion(
                description="Invoice drafts are prepared for each settled revenue record and remain unsent",
                measurable=True,
            )
        )
    if "read_email" in outcomes:
        success.append(
            SuccessCriterion(
                description="Requested Gmail messages are returned with provider evidence",
                measurable=True,
            )
        )
    if "read_crm" in outcomes:
        success.append(
            SuccessCriterion(
                description="Requested CRM records are returned with source evidence",
                measurable=True,
            )
        )
    if "query_salesforce" in outcomes:
        success.append(
            SuccessCriterion(
                description="The read-only Salesforce query returns records with provider evidence",
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
    if "persist_internal_crm" in outcomes:
        success.append(
            SuccessCriterion(
                description="Every Ajenda internal CRM prospect record is persisted, verified by readback, and has an opportunity projection",
                measurable=True,
            )
        )
    if "read_linkedin" in outcomes:
        success.append(
            SuccessCriterion(
                description="LinkedIn profile fields are returned with provider evidence",
                measurable=True,
            )
        )
    if "read_github" in outcomes:
        success.append(
            SuccessCriterion(
                description="GitHub repository metadata is returned with provider evidence",
                measurable=True,
            )
        )
    if "read_contacts" in outcomes:
        success.append(
            SuccessCriterion(
                description="Google Contacts records are returned with provider evidence",
                measurable=True,
            )
        )
    if "read_business_profile" in outcomes:
        success.append(
            SuccessCriterion(
                description="Evidence-backed Ajenda company facts are returned from approved business profile or governed memory",
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


def _segment_clauses(text: str, *, protected_spans: list[str] | None = None) -> list[str]:
    """Split only when a separator introduces a new imperative or policy clause."""

    working = text
    placeholders: list[tuple[str, str]] = []
    # Do not treat thousand-separator commas in amounts ($50,000) as clause breaks.
    for index, match in enumerate(re.finditer(r"\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?", working)):
        placeholder = f"__AJENDA_AMOUNT_{index}__"
        token = match.group(0)
        working = working.replace(token, placeholder, 1)
        placeholders.append((placeholder, token))
    for index, span in enumerate(protected_spans or []):
        token = (span or "").strip()
        if not token or " and " not in token.lower():
            continue
        placeholder = f"__AJENDA_ENTITY_{index}__"
        # Case-insensitive single replacement of the entity name span.
        pattern = re.compile(re.escape(token), flags=re.IGNORECASE)
        if pattern.search(working) is None:
            continue
        working = pattern.sub(placeholder, working, count=1)
        placeholders.append((placeholder, token))
    parts: list[str] = []
    for sentence in _CLAUSE_SENTENCE_SPLIT.split(working):
        sentence = sentence.strip(" ,;")
        if not sentence:
            continue
        if _COORDINATED_PROHIBITION_START.match(sentence):
            parts.append(sentence.strip(" ,.;"))
            continue
        parts.extend(part.strip(" ,.;") for part in _CLAUSE_SPLIT.split(sentence) if part and part.strip(" ,.;"))
    restored: list[str] = []
    for part in parts:
        restored_part = part
        for placeholder, token in placeholders:
            restored_part = restored_part.replace(placeholder, token)
        restored.append(restored_part)
    return restored if restored else [text.strip()]


def _classify_clause(
    clause: str,
    *,
    profile_mission: bool = False,
    external_action_forbidden: bool = False,
    business_income_review: bool = False,
    goal_progress_evaluation: bool = False,
) -> tuple[list[CanonicalOutcome], bool, bool]:
    """Return (outcomes, material, recognized)."""

    lower = clause.lower()
    if business_income_review and _BUSINESS_REVIEW_CLAUSE.match(clause.strip()):
        return ["review_business_income"], True, True
    if goal_progress_evaluation and re.match(
        r"^(?:return|provide|include|list)\b.*\b(?:status|confidence|kpi|progress\s+gaps?|evidence\s+gaps?|explanations?)\b",
        clause.strip(),
        flags=re.IGNORECASE,
    ):
        return ["evaluate_goal_progress"], True, True
    # A detailed multi-field deliverable list is not represented by the
    # canonical outcome contract. Do not let field names such as "research"
    # or "drafts" silently authorize a partial interpretation.
    if not profile_mission and _REPORT_SYNTHESIS_CLAUSE.match(clause.strip()):
        return ["synthesize_research_report"], True, True
    if not profile_mission and _DETAILED_RETURN_DELIVERABLE.match(clause.strip()):
        return [], True, False
    clause_deliverable = extract_deliverable_request(clause)
    if clause_deliverable is not None and clause_deliverable.fully_understood:
        # Leave typed field lists unmatched here so the dedicated deliverable
        # coverage layer can account them as deliverables, not action outcomes.
        return [], True, False
    # Instructions that explicitly classify source text as untrusted are
    # safety metadata, not an external action request or an unmatched mission
    # clause. Keep them visible to the caller without turning quoted verbs
    # such as “send” into requested outcomes.
    if _contains_any(lower, _PROMPT_INJECTION_PATTERNS):
        return [], False, True
    outcomes: list[CanonicalOutcome] = []
    profile_read = _contains_any(lower, _BUSINESS_PROFILE_READ_PATTERNS)
    profile_context = _contains_any(lower, _BUSINESS_PROFILE_CONTEXT_PATTERNS)
    if profile_read or (profile_mission and _contains_any(lower, _BUSINESS_PROFILE_DELIVERABLE_PATTERNS)):
        outcomes.append("read_business_profile")
    email_read = _contains_any(lower, _EMAIL_READ_PATTERNS)
    internal_crm_requested = _contains_any(lower, _INTERNAL_CRM_PATTERNS)
    crm_write_requested = _contains_any(lower, _CRM_UPDATE_PATTERNS) and not _contains_any(
        lower, _CRM_NEGATION_PATTERNS
    )
    internal_crm_read = (
        _contains_any(lower, _INTERNAL_CRM_READ_PATTERNS)
        and not _contains_any(lower, _INTERNAL_CRM_READ_NEGATION_PATTERNS)
        and not _CRM_READBACK_VERIFICATION_PATTERN.search(lower)
    )
    crm_read = (
        (internal_crm_read or (_contains_any(lower, _CRM_READ_PATTERNS) and not internal_crm_requested))
        and (internal_crm_read or not _contains_any(lower, _CRM_READ_NEGATION_PATTERNS))
        and (internal_crm_read or not crm_write_requested)
        and (internal_crm_read or not _contains_any(lower, _CRM_NEGATION_PATTERNS))
    )
    salesforce_query = _contains_any(lower, _SALESFORCE_QUERY_PATTERNS)
    connector_read = email_read or crm_read or salesforce_query
    # Trailing "summarize the messages/record" after a read is covered by list/read path.
    if (
        re.search(r"\bsummarize\b.{0,40}\b(?:messages?|emails?|records?|results?)\b", lower)
        and not connector_read
        and not internal_crm_requested
    ):
        return [], False, True
    # "from HubSpot CRM records" is a source qualifier for prospect research, not only CRM read.
    hubspot_as_source = bool(
        re.search(r"\bfrom\s+(?:the\s+)?hubspot\b", lower) or re.search(r"\bcompanies\b.*\bhubspot\b", lower)
    )
    explicit_prospect_research = bool(re.search(r"\b(?:prospects?|competitors?|companies\s+in)\b", lower))
    if _contains_any(lower, _RESEARCH_PATTERNS) and (
        not connector_read or explicit_prospect_research or hubspot_as_source
    ):
        # Prefer market research when "companies in X from HubSpot" — source is HubSpot, job is discover.
        if hubspot_as_source and re.search(r"\bcompanies\s+in\b|\bprospects?\b", lower):
            outcomes.append("research_prospects")
        elif not connector_read or explicit_prospect_research:
            outcomes.append("research_prospects")
    if _contains_any(lower, _QUALIFY_PATTERNS) and not salesforce_query:
        outcomes.append("qualify_prospects")
    if _contains_any(lower, _OBSERVE_CONTACT_PATTERNS):
        outcomes.append("observe_contacts")
    if _contains_any(lower, _ENRICH_PATTERNS):
        outcomes.append("enrich_contacts")
    if email_read:
        outcomes.append("read_email")
    if crm_read and not (hubspot_as_source and "research_prospects" in outcomes):
        outcomes.append("read_crm")
    if salesforce_query:
        outcomes.append("query_salesforce")
    # Wave A operator reads (before write/publish so "linkedin profile" is not publish).
    if _contains_any(lower, _LINKEDIN_READ_PATTERNS) and not _contains_any(lower, _PUBLISH_PATTERNS):
        outcomes.append("read_linkedin")
    if _contains_any(lower, _GITHUB_READ_PATTERNS):
        outcomes.append("read_github")
    # Contacts read only when not a CRM write ("add/save to contacts").
    if (
        _contains_any(lower, _CONTACTS_READ_PATTERNS)
        and not _contains_any(lower, _CRM_UPDATE_PATTERNS)
        and not _contains_any(lower, _NO_EXTERNAL_ACTION_PATTERNS)
    ):
        outcomes.append("read_contacts")
    if _contains_any(lower, _DRAFT_PATTERNS):
        outcomes.append("prepare_outreach")
    if _contains_any(lower, _SEND_PATTERNS) and not _contains_any(lower, _NO_SEND_PATTERNS):
        outcomes.append("send_outreach")
    if _contains_any(lower, _CALENDAR_PATTERNS):
        outcomes.append("read_calendar")
    if _contains_any(lower, _CRM_UPDATE_PATTERNS) and not _contains_any(lower, _CRM_NEGATION_PATTERNS):
        outcomes.append("persist_internal_crm" if internal_crm_requested else "update_crm")
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
        + _NO_EXTERNAL_ACTION_PATTERNS
        + (_BUSINESS_PROFILE_READ_PATTERNS if profile_mission else ())
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
            r"\breturn\b",
        ),
    )
    if profile_context:
        material = True
        recognized = True
    # Bare location/count fragments treated as material when short.
    if not material and (re.search(r"\b\d+\b", lower) or len(clause.split()) <= 4):
        material = True
    recognized = (
        bool(outcomes)
        or profile_context
        or _contains_any(
            lower,
            _NO_SEND_PATTERNS + _CONDITIONAL_SEND_PATTERNS + _CRM_NEGATION_PATTERNS + _NO_EXTERNAL_ACTION_PATTERNS,
        )
    )
    if external_action_forbidden and re.search(
        r"\b(?:browse|contact|send|modify|perform)\b|\bexternal action\b", lower
    ):
        material = True
        recognized = True
    # Industry+location span is recognized material even without a verb.
    if profile_mission and _contains_any(lower, _BUSINESS_PROFILE_DELIVERABLE_PATTERNS):
        material = True
        recognized = True
    if _INDUSTRY_LOCATION.search(clause):
        material = True
        recognized = True
    return outcomes, material, recognized
