"""Ability vocab + connector capability schema for composition."""

from __future__ import annotations

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
