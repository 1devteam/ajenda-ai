"""Connector compilation from schema-validated mission intent."""

from __future__ import annotations

import pytest

from backend.services.mission_composition.action_inputs import build_action_input
from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
from backend.services.mission_composition.connector_capabilities import (
    connector_defers_op,
    connector_supports_op,
    restatement_for_deferred_op,
)
from backend.services.mission_composition.contracts import TargetEntity
from backend.services.mission_composition.plan_compiler import compile_planned_steps
from backend.services.tools.salesforce_actions import SalesforceSoqlReadInput
from backend.services.tools.schemas import RecordWriteInput
from tests.mission_interpreter_fakes import ready_intent


def _compile(intent, *, ids: set[str] | None = None, integrations: set[str] | None = None):  # type: ignore[no-untyped-def]
    jobs = route_jobs_for_intent(intent)
    selections, missing = resolve_jobs(
        jobs,
        intent=intent,
        connected_credential_ids=ids or set(),
        connected_integrations=integrations or set(),
    )
    return compile_planned_steps(selections, intent=intent), selections, missing


def test_calendar_read_compiles_reviewed_day_window_and_requires_connection() -> None:
    intent = ready_intent(
        "wuts on cal july 28 2026",
        interpreted_instruction="Read my Google Calendar events for July 28, 2026.",
        outcomes=("read_calendar",),
    )
    _steps, selections, missing = _compile(intent)
    assert selections[0].action_name == "google_calendar.events_read"
    assert selections[0].readiness == "connection_required"
    assert missing[0]["provider"] == "google_calendar"

    steps, _selections, missing = _compile(
        intent,
        ids={"google-calendar-read"},
        integrations={"google_calendar"},
    )
    assert missing == []
    assert steps[0].tool_input["start"] == "2026-07-28T00:00:00Z"
    assert steps[0].tool_input["end"] == "2026-07-29T00:00:00Z"


def test_gmail_query_preserves_sender_keywords_and_time_scope() -> None:
    intent = ready_intent(
        "gmial alce invoces wk",
        interpreted_instruction="Search Gmail from Alice for Acme invoices last week.",
        outcomes=("read_email",),
    )
    steps, _selections, missing = _compile(intent, ids={"gmail-email"}, integrations={"gmail"})
    assert missing == []
    assert steps[0].tool_input["query"] == 'in:inbox newer_than:7d from:Alice "Acme invoices"'


def test_salesforce_named_contact_and_date_filter_compile_read_only_soql() -> None:
    intent = ready_intent(
        "sf contacts alice 30d",
        interpreted_instruction="Query Salesforce for contacts named Alice modified in the last 30 days.",
        outcomes=("query_salesforce",),
        quantity=10,
    )
    steps, _selections, missing = _compile(
        intent,
        ids={"salesforce-read"},
        integrations={"salesforce"},
    )
    assert missing == []
    assert steps[0].tool_input["soql"] == (
        "SELECT Id, Name, Email, AccountId, LastModifiedDate FROM Contact "
        "WHERE Name LIKE '%Alice%' AND LastModifiedDate = LAST_N_DAYS:30 LIMIT 10"
    )


def test_unsupported_salesforce_filter_fails_closed() -> None:
    intent = ready_intent(
        "sf accts active",
        interpreted_instruction="Query Salesforce accounts where status is active.",
        outcomes=("query_salesforce",),
    )
    with pytest.raises(ValueError, match="cannot be compiled safely"):
        _compile(intent, ids={"salesforce-read"}, integrations={"salesforce"})


def test_hubspot_source_cannot_fall_back_to_public_web() -> None:
    intent = ready_intent(
        "hubspot roofers austin",
        interpreted_instruction="Research 5 roofing companies in Austin using HubSpot CRM records.",
        outcomes=("research_prospects",),
        quantity=5,
        targets=[
            TargetEntity(
                type="market",
                industry="roofing",
                location="Austin",
                attributes={"research_source": "hubspot"},
            )
        ],
        context_requirements=["hubspot_source"],
    )
    steps, selections, missing = _compile(intent)
    assert steps == []
    assert all(item.action_name != "web.research" for item in selections)
    assert {item["provider"] for item in missing} == {"hubspot"}


def test_crm_write_uses_named_company_and_requires_hubspot() -> None:
    intent = ready_intent(
        "add acme roofing to crm",
        interpreted_instruction="Add Acme Roofing to the CRM contacts.",
        outcomes=("update_crm",),
        targets=[TargetEntity(type="company", name="Acme Roofing")],
    )
    _steps, selections, missing = _compile(intent)
    assert any(item.action_name == "gtm.crm_upsert" and item.readiness == "connection_required" for item in selections)
    assert any(item["provider"] == "hubspot" for item in missing)

    steps, _selections, missing = _compile(intent, ids={"hubspot-crm"}, integrations={"hubspot"})
    assert missing == []
    crm = next(step for step in steps if step.action_name == "gtm.crm_upsert")
    assert crm.tool_input["data"]["company"] == "Acme Roofing"
    assert crm.tool_input["context"]["binding_required"] is False


def test_connector_capability_contract_keeps_calendar_and_contacts_writes_deferred() -> None:
    assert connector_supports_op("google_calendar", "read") is True
    assert connector_supports_op("google_calendar", "write") is False
    assert connector_defers_op("google_calendar", "write") is True
    assert connector_supports_op("google_contacts", "write") is False
    assert connector_defers_op("google_contacts", "write") is True
    note = restatement_for_deferred_op(connector_id="google_calendar", op="write")
    assert note is not None
    assert "write" in note.lower()


def test_competitor_target_builds_specific_research_query() -> None:
    intent = ready_intent(
        "rsearch 5 comp acme roofin nwa",
        interpreted_instruction=(
            "Research 5 competitors of Acme Roofing in Northwest Arkansas, score them, "
            "and prepare outreach drafts for the top 3."
        ),
        outcomes=("research_prospects", "qualify_prospects", "prepare_outreach"),
        quantity=5,
        targets=[
            TargetEntity(
                type="competitor_set",
                name="Acme Roofing",
                location="Northwest Arkansas",
            )
        ],
    )
    payload = build_action_input(action_name="web.research", intent=intent)
    assert payload["query"] == "competitors of Acme Roofing in Northwest Arkansas"


def test_page_read_uses_schema_validated_interpreter_url() -> None:
    intent = ready_intent(
        "review https://example.com/pricing",
        interpreted_instruction="Review https://example.com/pricing.",
        outcomes=("research_prospects",),
        targets=[
            TargetEntity(
                type="company",
                url="https://example.com/pricing",
            )
        ],
    )

    payload = build_action_input(action_name="web.page_read", intent=intent)

    assert payload == {"url": "https://example.com/pricing", "timeout_seconds": 8.0}


def test_gmail_read_requires_connection_and_compiles_bounded_query() -> None:
    intent = ready_intent(
        "chk gmial unread alice wk",
        interpreted_instruction=(
            "Check Gmail for unread replies from alice@example.com from the last week and summarize the messages."
        ),
        outcomes=("read_email",),
    )
    jobs = route_jobs_for_intent(intent)
    blocked, missing = resolve_jobs(jobs, intent=intent)
    assert blocked[0].readiness == "connection_required"
    assert any(item["provider"] == "gmail" for item in missing)

    selected, missing = resolve_jobs(jobs, intent=intent, connected_integrations={"gmail"})
    assert missing == []
    assert selected[0].action_name == "gtm.email_check"
    payload = build_action_input(action_name="gtm.email_check", intent=intent)
    assert payload["limit"] == 10
    assert payload["query"] == "in:inbox is:unread newer_than:7d from:alice@example.com"


@pytest.mark.parametrize(
    ("interpreted", "required", "forbidden"),
    [
        ("Read messages from Gmail.", ("in:inbox",), ("is:read",)),
        (
            "Search Gmail for messages from Johnson and Johnson.",
            ('from:"Johnson and Johnson"',),
            ("from:Johnson ",),
        ),
        (
            "Search Gmail for invoices from Alice last week.",
            ("from:Alice", "newer_than:7d"),
            ("from:Alice last",),
        ),
        (
            "Search Gmail for Acme invoices for the last week.",
            ('"Acme invoices"', "newer_than:7d"),
            ('"the"',),
        ),
        (
            "Search Gmail for messages from Alice about Acme invoices.",
            ("from:Alice", '"Acme invoices"'),
            ("from:Alice about",),
        ),
        (
            "Search Gmail for messages from The Walt Disney Company and summarize them.",
            ('from:"The Walt Disney Company"',),
            ('"from The Walt Disney Company"', "summarize"),
        ),
    ],
)
def test_gmail_query_preserves_reviewed_sender_scope(
    interpreted: str,
    required: tuple[str, ...],
    forbidden: tuple[str, ...],
) -> None:
    intent = ready_intent("broken gmail shorthand", interpreted_instruction=interpreted, outcomes=("read_email",))
    query = build_action_input(action_name="gtm.email_check", intent=intent)["query"]
    assert all(token in query for token in required)
    assert all(token not in query for token in forbidden)


def test_hubspot_read_uses_explicit_company_and_rejects_unrepresentable_scope() -> None:
    named = ready_intent(
        "hub acme",
        interpreted_instruction="Check HubSpot for Acme Roofing and summarize the CRM record.",
        outcomes=("read_crm",),
        targets=[TargetEntity(type="company", name="Acme Roofing")],
    )
    payload = build_action_input(action_name="sales.research", intent=named)
    assert payload["lead"]["company"] == "Acme Roofing"
    assert payload["context"]["require_external_crm"] is True

    unsupported = ready_intent(
        "hub deals",
        interpreted_instruction="Check HubSpot deals.",
        outcomes=("read_crm",),
        context_requirements=["hubspot_source"],
    )
    with pytest.raises(ValueError, match=r"scope|sales\.research"):
        build_action_input(action_name="sales.research", intent=unsupported)


def test_salesforce_opportunity_query_remains_read_only_and_bounded() -> None:
    intent = ready_intent(
        "sf opps 12 50000 qtr",
        interpreted_instruction=(
            "Query Salesforce for the top 12 open opportunities over $50,000 closing this quarter."
        ),
        outcomes=("query_salesforce",),
        quantity=12,
    )
    parsed = SalesforceSoqlReadInput.model_validate(
        build_action_input(action_name="salesforce.soql_read", intent=intent)
    )
    assert "FROM Opportunity" in parsed.soql
    assert "IsClosed = false" in parsed.soql
    assert "CloseDate = THIS_QUARTER" in parsed.soql
    assert "Amount > 50000" in parsed.soql
    assert "ORDER BY Amount DESC" in parsed.soql
    assert parsed.soql.endswith("LIMIT 12")


def test_ordinary_research_can_use_internal_sales_without_hubspot() -> None:
    intent = ready_intent(
        "find roofers",
        interpreted_instruction="Research 5 roofing companies in Austin.",
        outcomes=("research_prospects",),
        quantity=5,
        targets=[TargetEntity(type="market", industry="roofing", location="Austin")],
    ).model_copy(
        update={
            "forbidden_outcomes": ["web.research", "web.search", "web.page_read", "crm.research"],
        }
    )
    selected, missing = resolve_jobs(route_jobs_for_intent(intent), intent=intent)
    assert missing == []
    assert selected[0].action_name == "sales.research"
    assert selected[0].requires_connection is False


def test_sales_log_activity_input_still_matches_runtime_schema() -> None:
    intent = ready_intent(
        "log note acme",
        interpreted_instruction="Log a note about Acme Roofing in the pipeline.",
        outcomes=("update_crm",),
        targets=[TargetEntity(type="company", name="Acme Roofing")],
    )
    parsed = RecordWriteInput.model_validate(build_action_input(action_name="sales.log_activity", intent=intent))
    assert parsed.record_type == "activity"
    assert parsed.data["type"] == "note"
