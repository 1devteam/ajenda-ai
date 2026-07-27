"""Derive non-empty tool.invoke inputs from MissionIntent for composed graphs."""

from __future__ import annotations

from typing import Any

from backend.services.mission_composition.contracts import MissionIntent

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
        research_query = intent.objective.strip()[:400] if intent.objective.strip() else query
        return {
            "query": research_query,
            "company": industry,
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
        return {
            "recipient": "pending.binding@invalid.local",
            "topic": topic[:240],
            "tone": "professional",
            "prospects": [],
            "context": {
                "industry": industry,
                "location": location,
                "objective": intent.objective[:300],
                "binding_required": True,
                "binding_source": "upstream_enriched_prospects",
                "binding_path": "$.enriched_prospects",
                "compose_note": (
                    "Recipient stays non-deliverable until enrich yields a real contact email. "
                    "Draft content must still use bound prospect company/signals."
                ),
            },
        }
    if action_name == "sales.draft_followup":
        return {
            "recipient_name": "Prospect (pending enrichment)",
            "topic": f"Follow-up regarding {industry or 'our conversation'}",
            "tone": "professional",
            "context": {
                "company": company_label,
                "location": location,
                "binding_required": True,
                "binding_source": "upstream_enriched_prospects",
            },
        }
    if action_name == "gtm.email_send":
        return {
            "to": "pending.binding@invalid.local",
            "subject": f"Introduction — {industry or 'Ajenda'}",
            "body": "Prepared by mission composition; requires bound recipient and human review before send.",
            "context": {
                "objective": intent.objective[:300],
                "binding_required": True,
                "binding_source": "upstream_enriched_prospects",
                "binding_path": "$.enriched_prospects[*].email",
                "send_policy": intent.send_policy.model_dump(mode="json"),
            },
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

    return {"context": {"objective": intent.objective[:300], "query": query}}
