"""Derive non-empty tool.invoke inputs from MissionIntent for composed graphs."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.services.mission_composition.contracts import MissionIntent

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_NAMED_DAY = re.compile(
    r"\b(?P<month>january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(?P<year>\d{4}))?\b",
    re.IGNORECASE,
)


def _calendar_window_from_objective(objective: str) -> tuple[str | None, str | None]:
    text = (objective or "").strip()
    named = _NAMED_DAY.search(text)
    if not named:
        return None, None
    month_num = _MONTHS.get(named.group("month").lower())
    if month_num is None:
        return None, None
    day = int(named.group("day"))
    year = int(named.group("year") or datetime.now(tz=UTC).year)
    try:
        start = datetime(year, month_num, day, 0, 0, 0, tzinfo=UTC)
    except Exception:
        return None, None
    end = start + timedelta(days=1)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


_DEFAULT_PROSPECT_COUNT = 3


def _prospect_count(intent: MissionIntent) -> int:
    """Use structured quantity only — never reparse success-criteria prose."""

    if intent.requested_quantity is not None:
        return max(1, min(int(intent.requested_quantity), 20))
    return _DEFAULT_PROSPECT_COUNT


def _target_bits(intent: MissionIntent) -> tuple[str | None, str | None, str]:
    entity = intent.target_entities[0] if intent.target_entities else None
    industry = entity.industry.strip() if entity and entity.industry else None
    location = entity.location.strip() if entity and entity.location else None
    parts: list[str] = []
    if industry:
        parts.append(industry)
    parts.append("companies")
    if location:
        parts.append(f"in {location}")
    query = " ".join(parts).strip()
    if not query or query == "companies":
        query = intent.objective.strip()[:400] or "prospect research"
    return industry, location, query


def _explicit_email(intent: MissionIntent) -> str | None:
    """Return a concrete recipient email from structured entities, if any."""

    for entity in intent.target_entities:
        if entity.email and "@" in entity.email:
            return entity.email.strip()
        attrs = entity.attributes if isinstance(entity.attributes, dict) else {}
        for key in ("email", "recipient_email", "to"):
            value = attrs.get(key)
            if isinstance(value, str) and "@" in value:
                return value.strip()
        if entity.type in {"email", "recipient", "contact"} and entity.name and "@" in entity.name:
            return entity.name.strip()
    return None


def build_action_input(*, action_name: str, intent: MissionIntent) -> dict[str, Any]:
    """Return a schema-valid-enough input payload for the action.

    Downstream steps may still rebind outputs via input_bindings; this ensures
    tool.invoke does not fail closed on empty required fields (e.g. web.research.query).
    """

    industry, location, query = _target_bits(intent)
    limit = _prospect_count(intent)
    company_label = industry or "prospect company"
    if location:
        company_label = f"{company_label} ({location})"

    lead: dict[str, Any] = {
        "company": company_label,
        "source": "mission_composition",
    }
    if industry:
        lead["industry"] = industry
    if location:
        lead["location"] = location

    if action_name == "web.research":
        entity = intent.target_entities[0] if intent.target_entities else None
        research_query = query
        if entity and entity.industry and entity.location:
            research_query = f"{entity.industry} companies in {entity.location}"
        elif entity and entity.name:
            research_query = entity.name
        return {
            "query": research_query[:400],
            "company": industry,
            "domain": entity.domain if entity else None,
            "fetch_public_page": False,
            "include_public_search": True,
            "limit": limit,
        }
    if action_name == "web.search":
        return {"query": query, "limit": limit}
    if action_name == "web.page_read":
        # Prefer domain-like attributes on target entities when present.
        # Never invent example.com — missing URL fails closed at composition.
        url: str | None = None
        for entity in intent.target_entities:
            attrs = entity.attributes if isinstance(entity.attributes, dict) else {}
            candidate = str(attrs.get("domain") or attrs.get("website") or attrs.get("url") or "").strip()
            if candidate:
                url = candidate if "://" in candidate else f"https://{candidate.lstrip('.')}"
                break
        if not url:
            raise ValueError(
                "web.page_read requires a target URL (entity attributes domain, website, or url); "
                "refusing to synthesize example.com"
            )
        return {"url": url, "timeout_seconds": 8.0}
    if action_name == "http.request":
        return {"method": "GET", "url": "https://example.com", "timeout_seconds": 5.0}
    if action_name in {"sales.research", "crm.research"}:
        return {"lead": lead}
    if action_name in {"sales.qualify", "sales.score_lead", "sales.recommend_next_action"}:
        return {
            "lead": lead,
            "prospects": [],
            "context": {
                "industry": industry,
                "location": location,
                "objective": intent.objective[:300],
                "binding_required": True,
                "binding_source": "upstream_prospect_candidates",
                "requested_quantity": limit,
            },
        }
    if action_name == "gtm.lead_enrich":
        return {
            "company": company_label,
            "prospects": [],
            "context": {
                "industry": industry,
                "location": location,
                "objective": intent.objective[:300],
                "binding_required": True,
                "binding_source": "upstream_qualified_prospects",
            },
        }
    if action_name == "gtm.email_draft":
        topic = f"Introduction — {industry}" if industry else "Introduction"
        if location:
            topic = f"{topic} ({location})"
        explicit = _explicit_email(intent)
        recipient = explicit or "pending.binding@invalid.local"
        if explicit:
            compose_note = "Recipient taken from explicit address in the mission instruction."
            binding_required = False
            binding_source = "explicit_recipient"
        else:
            compose_note = (
                "Recipient stays non-deliverable until enrich yields a real contact email. "
                "Draft content must still use bound prospect company/signals."
            )
            binding_required = True
            binding_source = "upstream_enriched_prospects"
        return {
            "recipient": recipient,
            "topic": topic[:240],
            "tone": "professional",
            "prospects": [],
            "context": {
                "industry": industry,
                "location": location,
                "objective": intent.objective[:300],
                "binding_required": binding_required,
                "binding_source": binding_source,
                "binding_path": "$.enriched_prospects" if binding_required else None,
                "compose_note": compose_note,
            },
        }
    if action_name == "sales.draft_followup":
        explicit = _explicit_email(intent)
        recipient_name = explicit or "Prospect (pending enrichment)"
        return {
            "recipient_name": recipient_name,
            "topic": f"Follow-up regarding {industry or 'our conversation'}",
            "tone": "professional",
            "context": {
                "company": company_label,
                "location": location,
                "binding_required": explicit is None,
                "binding_source": "explicit_recipient" if explicit else "upstream_enriched_prospects",
            },
        }
    if action_name == "gtm.email_send":
        explicit = _explicit_email(intent)
        return {
            "to": explicit or "pending.binding@invalid.local",
            "subject": f"Introduction — {industry or 'Ajenda'}",
            "body": "Prepared by mission composition; requires bound recipient and human review before send.",
            "context": {
                "objective": intent.objective[:300],
                "binding_required": explicit is None,
                "binding_source": "explicit_recipient" if explicit else "upstream_enriched_prospects",
                "binding_path": None if explicit else "$.enriched_prospects[*].email",
                "send_policy": intent.send_policy.model_dump(mode="json"),
            },
        }
    if action_name == "gtm.email_check":
        return {"query": "in:inbox", "limit": limit}
    if action_name == "gtm.crm_upsert":
        # Market labels must not become static contacts; bind discovered prospects.
        named = None
        for entity in intent.target_entities:
            if entity.name and entity.type in {"company", "person", "contact"}:
                named = entity.name
                break
        return {
            "record_type": "contact",
            "data": {
                "company": named or "pending.binding.company",
                "industry": industry,
                "location": location,
            },
            "context": {
                "source": "mission_composition",
                "binding_required": named is None,
                "binding_source": "explicit_company" if named else "upstream_prospect_candidates",
                "binding_path": None if named else "$.prospect_candidates",
                "compose_note": (
                    "CRM write uses the named company from the instruction."
                    if named
                    else (
                        "CRM write must bind discovered/qualified prospect records — "
                        "refusing to upsert the market label alone."
                    )
                ),
            },
        }
    if action_name in {"record.search", "document.search", "retrieval.hybrid_search"}:
        return {"query": query, "limit": limit}
    if action_name == "google_calendar.events_read":
        start, end = _calendar_window_from_objective(
            intent.raw_instruction or intent.normalized_instruction or intent.objective
        )
        payload = {"calendar_id": "primary", "limit": max(limit, 20)}
        if start:
            payload["start"] = start
        if end:
            payload["end"] = end
        return payload
    if action_name == "calendar.read":
        return {"limit": limit}
    if action_name == "sales.log_activity":
        return {"lead": lead, "activity": {"type": "note", "summary": intent.objective[:240]}}
    if action_name == "record.write":
        return {
            "record_type": "account",
            "data": {"name": company_label, "industry": industry, "location": location},
        }

    return {"context": {"objective": intent.objective[:300], "query": query}}
