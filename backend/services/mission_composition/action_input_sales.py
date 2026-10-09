"""Sales, CRM, scoring, record, and finance action input builders."""

from __future__ import annotations

import re
from typing import Any

from backend.services.mission_composition.action_input_common import (
    _local_fixture_only,
    _prospect_count,
    _salesforce_soql,
    _target_bits,
    _source_instruction,
)
from backend.services.mission_composition.contracts import MissionIntent, is_ranking_only_instruction


def build_sales_action_input(
    *,
    action_name: str,
    intent: MissionIntent,
    vertical_role: str | None = None,
) -> dict[str, Any] | None:
    industry, location, query = _target_bits(intent)
    limit = _prospect_count(intent)
    primary_entity = intent.target_entities[0] if intent.target_entities else None
    explicit_company = primary_entity.name.strip() if primary_entity and primary_entity.name else None
    company_label = explicit_company or industry or "prospect company"
    if location:
        company_label = f"{company_label} ({location})"

    lead: dict[str, Any] = {"company": company_label, "source": "mission_composition"}
    if industry:
        lead["industry"] = industry
    if location:
        lead["location"] = location

    if action_name in {"sales.research", "crm.research"}:
        # Explicit HubSpot / CRM read jobs must fail closed on external errors —
        # never silently complete with Ajenda-brain internal records.
        require_external = "read_crm" in {str(o) for o in intent.requested_outcomes} or "hubspot_source" in {
            str(item) for item in intent.context_requirements
        }
        if require_external:
            crm_source = _source_instruction(intent).lower()
            # sales.research only searches by company/domain — reject scopes the adapter drops.
            unsupported_scope = False
            if re.search(r"\bdeals?\b|\bpipeline\b", crm_source) and not explicit_company:
                unsupported_scope = True
            if re.search(
                r"\b(?:modified|updated|changed)\b.{0,32}\b(?:last|past)\s+\d+\s+days?\b",
                crm_source,
            ):
                unsupported_scope = True
            if re.search(r"\blist\b.{0,24}\bcontacts?\b", crm_source) and not explicit_company:
                unsupported_scope = True
            # The current HubSpot adapter accepts company/domain lookup only.
            # Market, location, quantity, and competitor discovery cannot be
            # represented faithfully without inventing a company search term.
            if any(entity.type == "competitor_set" for entity in intent.target_entities):
                unsupported_scope = True
            if not explicit_company and (industry or location or intent.requested_quantity is not None):
                unsupported_scope = True
            if unsupported_scope:
                raise ValueError(
                    "HubSpot request scope (object type / date filter / contact list) cannot be "
                    "expressed by sales.research company search; refusing silent wrong-scope read"
                )
        return {
            "lead": lead,
            "context": {
                "require_external_crm": require_external,
                "crm_source": "hubspot" if require_external else "auto",
                "objective": intent.objective[:300],
            },
        }
    if action_name in {"sales.qualify", "sales.score_lead", "sales.recommend_next_action"}:
        local_fixture_only = _local_fixture_only(intent)
        qualification_quantity = intent.qualification_quantity or limit
        ranking_only = is_ranking_only_instruction(intent.objective)
        qualification_threshold = (
            5
            if local_fixture_only
            or intent.qualification_quantity is not None
            or "observe_contacts" in intent.requested_outcomes
            else 7
        )
        return {
            "lead": lead,
            "prospects": [],
            "context": {
                "industry": industry,
                "location": location,
                "objective": intent.objective[:300],
                "binding_required": True,
                "binding_source": "upstream_prospect_candidates",
                "requested_quantity": qualification_quantity,
                "mission_specific_scoring": True,
                "qualification_threshold_10": qualification_threshold,
                "ranking_only": ranking_only,
                "provider_source": "hubspot" if "hubspot_source" in intent.context_requirements else None,
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
    if action_name == "salesforce.soql_read":
        return {"soql": _salesforce_soql(intent), "api_version": "v59.0"}
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
    if action_name == "sales.log_activity":
        return {
            "record_type": "activity",
            "data": {
                "lead": lead,
                "type": "note",
                "summary": intent.objective[:240],
            },
        }
    if action_name == "record.write":
        role = (vertical_role or "").strip().lower()
        workflow_context = (
            "gtm"
            if role in {"vertical.gtm", "vertical.sales", "vertical.email"}
            else ("vertical" if role.startswith("vertical.") else "crm")
        )
        return {
            "record_type": "contact",
            "data": {},
            "context": {
                "source": "mission_composition",
                "binding_required": True,
                "prospect_candidates": [],
                "qualified_prospects": [],
                "observed_contacts": [],
                "workflow_context": workflow_context,
            },
        }
    if action_name in {"vertical.finance.prepare_reconciliation", "vertical.finance.prepare_invoice_drafts"}:
        return {
            "revenue_records": [],
            "context": {"binding_required": True, "binding_source": "upstream_revenue_records"},
        }

    return None
