from __future__ import annotations

from typing import Any, Literal, TypedDict

BrainMissionTier = Literal["prepare/read", "prepare", "perform (internal)", "perform (capstone)", "read"]


class BrainMissionSpec(TypedDict):
    mission_id: str
    mission: str
    outcome: str
    action: str
    tier: BrainMissionTier
    side_effect_class: str
    input: dict[str, Any]
    optional_credential: bool


BRAIN_MISSIONS: tuple[BrainMissionSpec, ...] = (
    {
        "mission_id": "M1",
        "mission": "M1 — Remember who we are",
        "outcome": "Search governed memory for company facts from business profile.",
        "action": "retrieval.hybrid_search",
        "tier": "prepare/read",
        "side_effect_class": "none",
        "input": {"query": "Ajenda AI products services", "limit": 5},
        "optional_credential": False,
    },
    {
        "mission_id": "M2",
        "mission": "M2 — Find accounts in our book",
        "outcome": "Search internal account records.",
        "action": "record.search",
        "tier": "read",
        "side_effect_class": "none",
        "input": {"record_type": "account", "query": "Ajenda", "limit": 5},
        "optional_credential": False,
    },
    {
        "mission_id": "M3",
        "mission": "M3 — Research a prospect on the web",
        "outcome": "Combine business context with public web signals.",
        "action": "web.research",
        "tier": "prepare/read",
        "side_effect_class": "none",
        "input": {
            "query": "governed mission runtime SaaS",
            "company": "Ajenda AI",
            "domain": "ajenda.ai",
            "fetch_public_page": True,
            "limit": 3,
        },
        "optional_credential": False,
    },
    {
        "mission_id": "M4",
        "mission": "M4 — Qualify an inbound lead",
        "outcome": "Score fit and explain qualification.",
        "action": "sales.qualify",
        "tier": "prepare",
        "side_effect_class": "none",
        "input": {"lead": {"company": "Northwind Logistics", "title": "VP Operations", "source": "inbound"}},
        "optional_credential": False,
    },
    {
        "mission_id": "M5",
        "mission": "M5 — Score lead and recommend next action",
        "outcome": "Prioritize pipeline and suggest next step.",
        "action": "sales.recommend_next_action",
        "tier": "prepare",
        "side_effect_class": "none",
        "input": {"lead": {"company": "Northwind Logistics", "score": 72, "stage": "discovery"}},
        "optional_credential": False,
    },
    {
        "mission_id": "M6",
        "mission": "M6 — Enrich company/contact hints",
        "outcome": "Structured enrich payload for outreach prep.",
        "action": "gtm.lead_enrich",
        "tier": "prepare",
        "side_effect_class": "none",
        "input": {"company": "Northwind Logistics", "domain": "northwind-logistics.example"},
        "optional_credential": False,
    },
    {
        "mission_id": "M7",
        "mission": "M7 — Draft introduction email",
        "outcome": "Prepare (not send) a first-touch email.",
        "action": "gtm.email_draft",
        "tier": "prepare",
        "side_effect_class": "none",
        "input": {
            "recipient": "ops@northwind-logistics.example",
            "topic": "Ajenda clerical worker pilot",
            "tone": "professional",
            "context": {"goal": "Introduce governed AI missions for back-office work."},
        },
        "optional_credential": False,
    },
    {
        "mission_id": "M8",
        "mission": "M8 — Draft sales follow-up",
        "outcome": "Prepare follow-up copy and persist activity context.",
        "action": "sales.draft_followup",
        "tier": "prepare",
        "side_effect_class": "none",
        "input": {
            "recipient_name": "Jordan",
            "topic": "workflow review after intro",
            "tone": "professional",
            "context": {"company": "Northwind Logistics"},
        },
        "optional_credential": False,
    },
    {
        "mission_id": "M9",
        "mission": "M9 — Log prospect in internal pipeline",
        "outcome": "Perform internal CRM write (no external HubSpot required).",
        "action": "gtm.crm_upsert",
        "tier": "perform (internal)",
        "side_effect_class": "internal_write",
        "input": {
            "record_type": "contact",
            "data": {
                "email": "jordan.lee@northwind-logistics.example",
                "firstname": "Jordan",
                "lastname": "Lee",
                "company": "Northwind Logistics",
            },
        },
        "optional_credential": False,
    },
    {
        "mission_id": "M10",
        "mission": "M10 — Research lead against our records",
        "outcome": "Brain-first sales research (plugin CRM optional upgrade).",
        "action": "sales.research",
        "tier": "prepare/read",
        "side_effect_class": "none",
        "input": {"lead": {"company": "Northwind Logistics", "domain": "northwind-logistics.example"}},
        "optional_credential": True,
    },
    {
        "mission_id": "M11",
        "mission": "M11 — Capstone outreach loop",
        "outcome": "Research → draft → review → send → CRM in one governed clerical sequence.",
        "action": "gtm.email_send",
        "tier": "perform (capstone)",
        "side_effect_class": "external_send",
        "input": {
            "to": "ops@northwind-logistics.example",
            "context": {
                "capstone": True,
                "note": "Approve an M7 draft in review queue, then send with artifact_id.",
            },
        },
        "optional_credential": False,
    },
    {
        "mission_id": "M12",
        "mission": "M12 — Search clerical library",
        "outcome": "Find governed document artifacts (ROI briefs, capability resumes, drafts).",
        "action": "document.search",
        "tier": "prepare/read",
        "side_effect_class": "internal_read",
        "input": {"query": "Ajenda capability ROI", "artifact_type": "roi_brief", "limit": 5},
        "optional_credential": False,
    },
)
