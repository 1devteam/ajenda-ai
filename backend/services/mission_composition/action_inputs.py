"""Derive non-empty tool.invoke inputs from MissionIntent for composed graphs."""

from __future__ import annotations

import re
from typing import Any

from backend.services.mission_composition.contracts import MissionIntent

_COUNT_RE = re.compile(r"\b(\d+|three|two|four|five|ten)\b", re.IGNORECASE)
_WORD_COUNTS = {"two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}


def _prospect_count(intent: MissionIntent) -> int:
    for criterion in intent.success_criteria:
        match = _COUNT_RE.search(criterion.description)
        if match is None:
            continue
        raw = match.group(1).lower()
        if raw.isdigit():
            return max(1, min(int(raw), 20))
        if raw in _WORD_COUNTS:
            return _WORD_COUNTS[raw]
    match = _COUNT_RE.search(intent.objective)
    if match is not None:
        raw = match.group(1).lower()
        if raw.isdigit():
            return max(1, min(int(raw), 20))
        if raw in _WORD_COUNTS:
            return _WORD_COUNTS[raw]
    return 3


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
        return {
            "query": query,
            "company": industry,
            "fetch_public_page": True,
            "limit": limit,
        }
    if action_name == "web.search":
        return {"query": query, "limit": limit}
    if action_name in {"sales.research", "crm.research"}:
        return {"lead": lead}
    if action_name in {"sales.qualify", "sales.score_lead", "sales.recommend_next_action"}:
        return {"lead": lead}
    if action_name == "gtm.lead_enrich":
        return {
            "company": company_label,
            "context": {
                "industry": industry,
                "location": location,
                "objective": intent.objective[:300],
            },
        }
    if action_name == "gtm.email_draft":
        topic = f"Introduction — {industry}" if industry else "Introduction"
        if location:
            topic = f"{topic} ({location})"
        return {
            "recipient": "prospect@example.com",
            "topic": topic[:240],
            "tone": "professional",
            "context": {
                "industry": industry,
                "location": location,
                "objective": intent.objective[:300],
                "compose_note": "Recipient may be rebound after enrichment.",
            },
        }
    if action_name == "sales.draft_followup":
        return {
            "recipient_name": "Prospect",
            "topic": f"Follow-up regarding {industry or 'our conversation'}",
            "tone": "professional",
            "context": {"company": company_label, "location": location},
        }
    if action_name == "gtm.email_send":
        return {
            "to": "prospect@example.com",
            "subject": f"Introduction — {industry or 'Ajenda'}",
            "body": "Prepared by mission composition; requires human review before send.",
            "context": {"objective": intent.objective[:300]},
        }
    if action_name == "gtm.email_check":
        return {"query": "in:inbox", "limit": limit}
    if action_name == "gtm.crm_upsert":
        return {
            "record_type": "contact",
            "data": {
                "company": company_label,
                "industry": industry,
                "location": location,
            },
            "context": {"source": "mission_composition"},
        }
    if action_name in {"record.search", "document.search", "retrieval.hybrid_search"}:
        return {"query": query, "limit": limit}
    if action_name == "google_calendar.events_read":
        return {"calendar_id": "primary", "limit": limit}
    if action_name == "calendar.read":
        return {"limit": limit}
    if action_name == "sales.log_activity":
        return {"lead": lead, "activity": {"type": "note", "summary": intent.objective[:240]}}
    if action_name == "record.write":
        return {
            "record_type": "account",
            "data": {"name": company_label, "industry": industry, "location": location},
        }

    # Safe default: never empty for query-shaped actions; otherwise empty dict is fine.
    return {"context": {"objective": intent.objective[:300], "query": query}}
