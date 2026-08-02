"""Ability vocab + connector capability schema for composition."""

from __future__ import annotations

import pytest

from backend.services.mission_composition.ability_vocab import match_outcome_phrases, phrase_maps_to_outcome
from backend.services.mission_composition.action_inputs import build_action_input
from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
from backend.services.mission_composition.connector_capabilities import (
    connector_defers_op,
    connector_supports_op,
    restatement_for_deferred_op,
)
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.tools.salesforce_actions import SalesforceSoqlReadInput
from backend.services.tools.schemas import RecordWriteInput


def test_score_them_maps_to_qualify() -> None:
    assert phrase_maps_to_outcome("score them") == "qualify_prospects"
    hits = match_outcome_phrases("score them and prepare drafts")
    assert any(h.outcome == "qualify_prospects" for h in hits)


def test_score_them_mission_composes_ready() -> None:
    intent = interpret_instruction(
        "Research five competitors of Acme Roofing in Northwest Arkansas, "
        "score them, and prepare outreach drafts for the top three."
    )
    assert "research_prospects" in intent.requested_outcomes
    assert "qualify_prospects" in intent.requested_outcomes
    assert "prepare_outreach" in intent.requested_outcomes
    assert intent.unmatched_material_clauses == []
    assert not any(c.field == "clause_coverage" for c in intent.ambiguity)
    assert intent.interpretation_ready is True
    assert intent.coverage_score >= 0.99
    # Structured competitor target — not the lossy "requested market" restatement.
    assert intent.target_entities
    entity = intent.target_entities[0]
    assert entity.type == "competitor_set"
    assert entity.name == "Acme Roofing"
    assert entity.location is not None
    assert "Northwest Arkansas" in (entity.location or "")
    assert "requested market" not in intent.objective.lower()
    assert "Acme Roofing" in intent.objective or "competitors of Acme" in intent.objective.lower()


def test_competitors_of_builds_usable_web_research_query() -> None:
    from backend.services.mission_composition.action_inputs import build_action_input

    intent = interpret_instruction(
        "Research five competitors of Acme Roofing in Northwest Arkansas, "
        "score them, and prepare outreach drafts for the top three."
    )
    payload = build_action_input(action_name="web.research", intent=intent)
    query = str(payload["query"])
    assert "Acme Roofing" in query
    assert "Northwest Arkansas" in query
    assert "competitors" in query.lower()
    assert "requested market" not in query.lower()
    assert "Identify and prepare outreach" not in query


def test_rank_and_best_also_qualify() -> None:
    intent = interpret_instruction(
        "Find five roofing companies in Austin, rank the strongest, and prepare draft emails for review."
    )
    assert "qualify_prospects" in intent.requested_outcomes


def test_calendar_write_uses_connector_schema_not_unknown_phrase() -> None:
    intent = interpret_instruction("Schedule a meeting with Bob tomorrow at 2pm on my calendar.")
    assert "read_calendar" not in intent.requested_outcomes
    assert any(c.field == "calendar_write" for c in intent.ambiguity)
    assert not any(c.field == "requested_outcomes" for c in intent.ambiguity)
    text = " ".join(c.question for c in intent.ambiguity).lower()
    assert "google calendar" in text or "write" in text
    assert "runtime-bound" in text or "read" in text


def test_connector_capability_calendar_defers_write() -> None:
    assert connector_supports_op("google_calendar", "read") is True
    assert connector_supports_op("google_calendar", "write") is False
    assert connector_defers_op("google_calendar", "write") is True
    note = restatement_for_deferred_op(connector_id="google_calendar", op="write")
    assert note is not None
    assert "write" in note.lower()


def test_gmail_read_composes_registered_action_and_bounded_query() -> None:
    intent = interpret_instruction(
        "Check Gmail for unread replies from alice@example.com from the last week and summarize the messages."
    )

    assert intent.requested_outcomes == ["read_email"]
    assert intent.interpretation_ready is True
    assert not any(item.field == "send_permission" for item in intent.ambiguity)

    jobs = route_jobs_for_intent(intent)
    assert [job.job_key for job in jobs] == ["email.read_messages"]

    blocked, missing = resolve_jobs(jobs, intent=intent)
    assert blocked[0].readiness == "connection_required"
    assert any(item["provider"] == "gmail" for item in missing)

    selected, missing = resolve_jobs(jobs, intent=intent, connected_integrations={"gmail"})
    assert missing == []
    assert selected[0].action_name == "gtm.email_check"
    assert selected[0].readiness == "ready"

    payload = build_action_input(action_name="gtm.email_check", intent=intent)
    assert payload["limit"] == 10
    assert "in:inbox" in payload["query"]
    assert "is:unread" in payload["query"]
    assert "newer_than:7d" in payload["query"]
    assert "from:alice@example.com" in payload["query"]


def test_hubspot_read_uses_explicit_company_and_requires_connection() -> None:
    intent = interpret_instruction("Check HubSpot for Acme Roofing and summarize the CRM record.")

    assert intent.requested_outcomes == ["read_crm"]
    assert intent.interpretation_ready is True
    assert intent.target_entities[0].name == "Acme Roofing"

    jobs = route_jobs_for_intent(intent)
    assert [job.job_key for job in jobs] == ["crm.read_records"]
    blocked, missing = resolve_jobs(jobs, intent=intent)
    assert blocked[0].readiness == "connection_required"
    assert any(item["provider"] == "hubspot" for item in missing)

    selected, missing = resolve_jobs(jobs, intent=intent, connected_integrations={"hubspot"})
    assert missing == []
    assert selected[0].action_name == "sales.research"
    assert selected[0].readiness == "ready"

    payload = build_action_input(action_name="sales.research", intent=intent)
    assert payload["lead"]["company"] == "Acme Roofing"
    assert payload["context"]["require_external_crm"] is True


def test_salesforce_query_composes_read_only_soql_and_requires_connection() -> None:
    intent = interpret_instruction(
        "Query Salesforce for the top 12 open opportunities over $50,000 closing this quarter."
    )

    assert intent.requested_outcomes == ["query_salesforce"]
    assert intent.interpretation_ready is True

    jobs = route_jobs_for_intent(intent)
    assert [job.job_key for job in jobs] == ["crm.query_salesforce"]
    blocked, missing = resolve_jobs(jobs, intent=intent)
    assert blocked[0].readiness == "connection_required"
    assert any(item["provider"] == "salesforce" for item in missing)

    selected, missing = resolve_jobs(jobs, intent=intent, connected_integrations={"salesforce"})
    assert missing == []
    assert selected[0].action_name == "salesforce.soql_read"
    assert selected[0].readiness == "ready"

    payload = build_action_input(action_name="salesforce.soql_read", intent=intent)
    parsed = SalesforceSoqlReadInput.model_validate(payload)
    assert "FROM Opportunity" in parsed.soql
    assert "IsClosed = false" in parsed.soql
    assert "CloseDate = THIS_QUARTER" in parsed.soql
    assert "Amount > 50000" in parsed.soql
    assert "ORDER BY Amount DESC" in parsed.soql
    assert parsed.soql.endswith("LIMIT 12")


def test_connector_read_clause_does_not_invent_web_research() -> None:
    intent = interpret_instruction("Find Acme Roofing in HubSpot.")

    assert intent.requested_outcomes == ["read_crm"]
    assert "research_prospects" not in intent.requested_outcomes
    assert intent.unmatched_material_clauses == []


def test_score_without_prospect_context_does_not_map_qualify() -> None:
    hits = match_outcome_phrases("Research conversion rates and grade the report")
    assert not any(h.outcome == "qualify_prospects" for h in hits)


def test_hubspot_email_records_do_not_require_gmail() -> None:
    intent = interpret_instruction("Check HubSpot for email records for Acme")
    assert "read_crm" in intent.requested_outcomes
    assert "read_email" not in intent.requested_outcomes


def test_salesforce_named_contact_filter_compiles() -> None:
    intent = interpret_instruction("Query Salesforce for contacts named Alice")
    payload = build_action_input(action_name="salesforce.soql_read", intent=intent)
    assert "FROM Contact" in payload["soql"]
    assert "Name LIKE '%Alice%'" in payload["soql"]


def test_google_contacts_write_is_deferred() -> None:
    assert connector_supports_op("google_contacts", "write") is False
    assert connector_defers_op("google_contacts", "write") is True


def test_competitor_name_with_and_stays_ready() -> None:
    intent = interpret_instruction(
        "Research competitors of Johnson and Johnson in Austin and prepare draft emails without sending."
    )
    assert intent.target_entities
    assert intent.target_entities[0].name == "Johnson and Johnson"
    assert not any(c.field == "clause_coverage" for c in intent.ambiguity)


def test_gmail_read_imperative_does_not_add_is_read_filter() -> None:
    intent = interpret_instruction("Read messages from Gmail")
    payload = build_action_input(action_name="gtm.email_check", intent=intent)
    assert "in:inbox" in payload["query"]
    assert "is:read" not in payload["query"]


def test_gmail_query_preserves_from_name_and_for_keywords() -> None:
    intent = interpret_instruction("Search Gmail for Acme invoices from Alice")
    payload = build_action_input(action_name="gtm.email_check", intent=intent)
    query = payload["query"]
    assert "from:Alice" in query or "from:alice" in query.lower()
    assert "Acme" in query or "invoices" in query.lower()


def test_salesforce_named_contact_stops_before_date_filter() -> None:
    intent = interpret_instruction("Query Salesforce for contacts named Alice modified in the last 30 days")
    payload = build_action_input(action_name="salesforce.soql_read", intent=intent)
    assert "Name LIKE '%Alice%'" in payload["soql"]
    assert "Alice modified" not in payload["soql"]
    assert "LAST_N_DAYS:30" in payload["soql"]


def test_hubspot_deals_without_company_fails_closed() -> None:
    intent = interpret_instruction("Check HubSpot deals")
    assert "read_crm" in intent.requested_outcomes
    try:
        build_action_input(action_name="sales.research", intent=intent)
        raise AssertionError("expected ValueError for unsupported HubSpot scope")
    except ValueError as exc:
        assert "scope" in str(exc).lower() or "sales.research" in str(exc).lower()


def test_hubspot_source_research_does_not_dual_route_web_and_crm() -> None:
    intent = interpret_instruction("Research five roofing companies in Austin from HubSpot CRM records.")
    assert "research_prospects" in intent.requested_outcomes
    assert "read_crm" not in intent.requested_outcomes
    assert "hubspot_source" in intent.context_requirements

    jobs = route_jobs_for_intent(intent)
    assert [job.job_key for job in jobs] == ["research.discover_prospects"]
    # Without HubSpot: connection_required (not public web).
    blocked, missing = resolve_jobs(jobs, intent=intent)
    assert blocked[0].action_name == "sales.research"
    assert blocked[0].readiness == "connection_required"
    assert any(item["provider"] == "hubspot" for item in missing)
    # With HubSpot: CRM-bound sales.research, never web.research.
    selected, missing = resolve_jobs(jobs, intent=intent, connected_integrations={"hubspot"})
    assert missing == []
    assert selected[0].action_name == "sales.research"
    assert selected[0].readiness == "ready"

    try:
        build_action_input(action_name="sales.research", intent=intent)
        raise AssertionError("expected market-scoped HubSpot discovery to fail closed")
    except ValueError as exc:
        assert "scope" in str(exc).lower() or "company" in str(exc).lower()


def test_hubspot_source_named_competitor_discovery_fails_closed() -> None:
    intent = interpret_instruction("Research five competitors of Acme Roofing in Austin from HubSpot CRM records.")
    assert intent.target_entities[0].type == "competitor_set"
    assert intent.target_entities[0].name == "Acme Roofing"

    with pytest.raises(ValueError, match=r"scope|company|sales\.research"):
        build_action_input(action_name="sales.research", intent=intent)


def test_ordinary_research_keeps_internal_sales_research_without_hubspot() -> None:
    intent = interpret_instruction("Research five roofing companies in Austin.")
    intent = intent.model_copy(
        update={
            "forbidden_outcomes": [
                *intent.forbidden_outcomes,
                "web.research",
                "web.search",
                "web.page_read",
                "crm.research",
            ]
        }
    )
    jobs = route_jobs_for_intent(intent)
    selected, missing = resolve_jobs(jobs, intent=intent)
    assert missing == []
    assert selected[0].action_name == "sales.research"
    assert selected[0].readiness == "ready"
    assert selected[0].requires_connection is False


def test_optional_crm_job_uses_schema_valid_local_write_without_hubspot() -> None:
    from backend.services.mission_composition.plan_compiler import compile_planned_steps

    intent = interpret_instruction("Find three roofing companies in Austin and add them to contacts")
    jobs = route_jobs_for_intent(intent)

    selected, missing = resolve_jobs(jobs, intent=intent)
    crm_selection = next(item for item in selected if item.job_key == "crm.pipeline_maintenance")

    assert crm_selection.action_name == "record.write"
    assert crm_selection.readiness == "ready"
    assert missing == []
    assert any(
        item.action == "gtm.crm_upsert" and item.status == "connection_required" for item in crm_selection.alternatives
    )
    RecordWriteInput.model_validate(build_action_input(action_name=crm_selection.action_name, intent=intent))
    crm_step = next(
        step for step in compile_planned_steps(selected, intent=intent) if step.job_key == "crm.pipeline_maintenance"
    )
    assert crm_step.input_bindings
    assert all(binding["input_path"].startswith("$.input.data.") for binding in crm_step.input_bindings)


def test_sales_log_activity_composition_input_matches_runtime_schema() -> None:
    intent = interpret_instruction("Log a note about Acme Roofing in the pipeline")
    payload = build_action_input(action_name="sales.log_activity", intent=intent)

    parsed = RecordWriteInput.model_validate(payload)
    assert parsed.record_type == "activity"
    assert parsed.data["type"] == "note"


def test_gmail_sender_before_keyword_clause_preserves_material_scope() -> None:
    intent = interpret_instruction("Search Gmail for messages from Alice for Acme invoices")
    payload = build_action_input(action_name="gtm.email_check", intent=intent)
    query = payload["query"]
    assert "from:Alice" in query
    assert "Acme" in query
    assert "invoices" in query
    assert "from:Alice for" not in query


def test_gmail_sender_preserves_and_inside_organization_name() -> None:
    intent = interpret_instruction("Search Gmail for messages from Johnson and Johnson")
    payload = build_action_input(action_name="gtm.email_check", intent=intent)
    query = payload["query"]
    assert 'from:"Johnson and Johnson"' in query
    assert "from:Johnson " not in query


def test_gmail_from_stops_before_temporal_clause() -> None:
    intent = interpret_instruction("Search Gmail for invoices from Alice last week")
    payload = build_action_input(action_name="gtm.email_check", intent=intent)
    query = payload["query"]
    assert "from:Alice" in query
    assert "from:Alice last" not in query
    assert "newer_than:7d" in query


def test_gmail_temporal_for_clause_does_not_displace_subject_terms() -> None:
    intent = interpret_instruction("Search Gmail for Acme invoices for the last week")
    payload = build_action_input(action_name="gtm.email_check", intent=intent)
    query = payload["query"]
    assert '"Acme invoices"' in query
    assert "newer_than:7d" in query
    assert '"the"' not in query


def test_gmail_sender_clause_does_not_leak_into_keyword_phrase() -> None:
    intent = interpret_instruction("Search Gmail for messages from Alice and summarize them")
    payload = build_action_input(action_name="gtm.email_check", intent=intent)
    query = payload["query"]
    assert "from:Alice" in query
    assert '"from Alice and summarize them"' not in query
    assert "summarize" not in query


def test_gmail_long_sender_name_does_not_leak_into_keyword_phrase() -> None:
    intent = interpret_instruction("Search Gmail for messages from The Walt Disney Company and summarize them")
    payload = build_action_input(action_name="gtm.email_check", intent=intent)
    query = payload["query"]
    assert 'from:"The Walt Disney Company"' in query
    assert '"from The Walt Disney Company"' not in query
    assert "summarize" not in query


def test_gmail_sender_stops_before_keyword_preposition() -> None:
    intent = interpret_instruction("Search Gmail for messages from Alice about Acme invoices")
    payload = build_action_input(action_name="gtm.email_check", intent=intent)
    query = payload["query"]
    assert "from:Alice" in query
    assert '"Acme invoices"' in query
    assert "from:Alice about" not in query


def test_salesforce_name_keeps_and_inside_company() -> None:
    intent = interpret_instruction("Query Salesforce for accounts named Johnson and Johnson")
    payload = build_action_input(action_name="salesforce.soql_read", intent=intent)
    assert "Name LIKE '%Johnson and Johnson%'" in payload["soql"]
