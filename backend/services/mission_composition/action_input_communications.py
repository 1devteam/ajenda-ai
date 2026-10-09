"""Email, follow-up, send/check, and social publish action input builders."""

from __future__ import annotations

import re
from typing import Any

from backend.services.mission_composition.action_input_common import (
    _explicit_email,
    _gmail_query,
    _prospect_count,
    _target_bits,
)
from backend.services.mission_composition.contracts import MissionIntent


def build_communications_action_input(*, action_name: str, intent: MissionIntent) -> dict[str, Any] | None:
    industry, location, _ = _target_bits(intent)
    limit = _prospect_count(intent)
    primary_entity = intent.target_entities[0] if intent.target_entities else None
    explicit_company = primary_entity.name.strip() if primary_entity and primary_entity.name else None
    company_label = explicit_company or industry or "prospect company"
    if location:
        company_label = f"{company_label} ({location})"
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
        return {"query": _gmail_query(intent), "limit": max(limit, 10)}
    if action_name == "gtm.social_publish":
        # Build a schema-valid publish payload; never leave content empty.
        objective = (intent.objective or "").strip()
        lower_obj = objective.lower()
        platform = "linkedin"
        if "twitter" in lower_obj or re.search(r"\bx\b", lower_obj):
            platform = "twitter"
        elif "facebook" in lower_obj:
            platform = "facebook"
        result_based = any(
            isinstance(entity.attributes, dict) and entity.attributes.get("publish_result_based")
            for entity in intent.target_entities
        ) or bool(re.search(r"\b(?:post|publish|share)\s+(?:the\s+)?(?:results?|findings?|them)\b", lower_obj))
        if result_based:
            # Do not publish the mission command text; bind upstream research outputs.
            content = "Pending research results for social publish (bind after upstream research)."
            return {
                "platform": platform,
                "content": content[:280],
                "context": {
                    "objective": objective[:300],
                    "source": "mission_composition",
                    "binding_required": True,
                    "binding_source": "upstream_prospect_candidates",
                    "binding_path": "$.prospect_candidates",
                    "compose_note": (
                        "Result-based publish must bind research outputs; "
                        "refusing to post the raw instruction as content."
                    ),
                },
            }
        content = objective[:280] if objective else "Ajenda composed social update"
        if len(content) < 1:
            content = "Ajenda composed social update"
        return {
            "platform": platform,
            "content": content,
            "context": {
                "objective": objective[:300],
                "source": "mission_composition",
                "binding_required": False,
                "binding_source": "standalone_publish_content",
            },
        }
    return None
