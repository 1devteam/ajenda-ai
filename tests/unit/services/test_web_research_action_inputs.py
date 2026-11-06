"""Entity-first web.research inputs for composition graphs."""

from __future__ import annotations

import pytest

from backend.services.mission_composition.action_inputs import build_action_input
from backend.services.mission_composition.contracts import MissionIntent, TargetEntity
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.service import MissionCompositionService


def test_observe_web_page_is_a_distinct_browser_outcome() -> None:
    intent = interpret_instruction("Observe this web page https://example.com and extract its title")
    assert "observe_web_page" in intent.requested_outcomes


def test_observe_explicit_url_without_web_noun_is_a_browser_outcome() -> None:
    intent = interpret_instruction(
        "Observe https://example.com using a read-only browser session and extract the page title and visible body text."
    )
    assert intent.requested_outcomes == ["observe_web_page"]
    assert intent.interpretation_ready is True
    assert intent.target_entities[0].type == "web_page"
    assert intent.target_entities[0].url == "https://example.com"
    assert all(item.measurable for item in intent.success_criteria)
    assert intent.unmatched_material_clauses == []


def test_scrape_company_site_builds_compact_query_and_company() -> None:
    intent = interpret_instruction(
        "scrape absolute janitorial web site to find the contact information "
        "for quality control Sarah Bogert return contact info"
    )
    payload = build_action_input(action_name="web.research", intent=intent)
    query = str(payload["query"]).lower()
    # Must not dump the full imperative instruction as the DDG query.
    assert "return contact info" not in query
    assert "scrape" not in query
    assert "absolute" in query or "janitorial" in query or "sarah" in query
    assert payload.get("company")
    assert "absolute" in str(payload["company"]).lower() or "janitorial" in str(payload["company"]).lower()
    # Scrape language without a host still marks site-scoped research intent.
    assert payload.get("fetch_public_page") is True
    assert payload.get("include_public_search") is True


def test_market_research_query_prefers_industry_location() -> None:
    intent = interpret_instruction(
        "Find five roofing companies in Austin and draft personalized introductions. Do not send."
    )
    payload = build_action_input(action_name="web.research", intent=intent)
    query = str(payload["query"]).lower()
    assert "roofing" in query
    assert "austin" in query
    assert not query.startswith("find five")


def test_local_fixture_constraint_disables_public_search() -> None:
    intent = interpret_instruction(
        "Find five software companies in Austin and collect contacts using local fixture data only."
    )
    payload = build_action_input(action_name="web.research", intent=intent)
    assert payload["local_fixture_only"] is True
    assert payload["include_public_search"] is False


def test_public_web_only_constraint_excludes_internal_records_at_input_boundary() -> None:
    intent = interpret_instruction(
        "Find three early-stage SaaS companies in Austin using public web research only. "
        "Do not use CRM records, saved contacts, or internal data."
    )

    payload = build_action_input(action_name="web.research", intent=intent)

    assert "public_web_only" in intent.context_requirements
    assert payload["include_public_search"] is True
    assert payload["exclude_internal_records"] is True


def test_reference_company_business_category_compiles_as_evidence_requirement() -> None:
    instruction = (
        "Research 3 companies in the same business category as 1DevTeam. "
        "Produce an evidence-backed comparison report. Do not contact anyone or modify external systems."
    )

    intent = interpret_instruction(instruction)
    payload = build_action_input(action_name="web.research", intent=intent)

    assert intent.interpretation_ready is True
    assert intent.target_entities[0].name == "1DevTeam"
    assert intent.target_entities[0].attributes == {
        "research_mode": "related_business_type",
        "relation": "reference_company_business_type",
        "reference_company": "1DevTeam",
    }
    assert payload["company"] == "1DevTeam"
    assert payload["fetch_public_page"] is True
    assert payload["exclude_internal_records"] is True
    assert payload["context"]["relation_requirements"] == [
        {
            "relation": "reference_company_business_type",
            "reference_company": "1DevTeam",
            "reference_domain": None,
            "required_for": "prospect_search",
            "status": "awaiting_public_evidence",
        }
    ]
    assert payload["context"]["objective"] == instruction


@pytest.mark.parametrize(
    "instruction",
    [
        "Research 3 companies in the same business category as 1DevTeam.",
        "Find 3 companies similar to 1DevTeam.",
        "Discover 3 businesses like 1DevTeam.",
        "Research 3 providers comparable to 1DevTeam.",
        (
            "Research 3 United States companies comparable to 1DevTeam that provide custom software development "
            "and applied research services."
        ),
        "Look up 1DevTeam and find 3 prospects.",
        "Identify 3 peers related to 1DevTeam.",
        "Find 3 companies in the same line of business as 1DevTeam.",
        "Research 3 alternatives to 1DevTeam.",
        "Find 3 competitors similar to 1DevTeam.",
    ],
)
def test_reference_company_directives_share_one_relation_contract(instruction: str) -> None:
    intent = interpret_instruction(instruction)
    payload = build_action_input(action_name="web.research", intent=intent)

    assert intent.interpretation_ready is True
    assert intent.target_entities[0].attributes["relation"] == "reference_company_business_type"
    assert payload["relation_requirements"][0]["reference_company"] == "1DevTeam"
    assert payload["exclude_internal_records"] is True


def test_reference_company_url_becomes_relation_domain_not_generic_page() -> None:
    intent = interpret_instruction("Look up https://www.1devteam.com/about and find 3 prospects.")
    payload = build_action_input(action_name="web.research", intent=intent)

    assert intent.interpretation_ready is True
    assert intent.target_entities[0].type == "company"
    assert intent.target_entities[0].domain == "1devteam.com"
    assert payload["domain"] == "1devteam.com"
    assert payload["relation_requirements"][0]["reference_domain"] == "1devteam.com"


def test_full_reference_company_report_mission_does_not_invent_crm_write() -> None:
    instruction = (
        "Research 3 companies in the same business category as 1DevTeam. "
        "Produce a report covering company identity, services, industries, differentiators, locations, "
        "public contact links, evidence sources, confidence, and any unverifiable claims. "
        "Create a recommended next step for each company. Do not contact or modify external systems."
    )

    intent = interpret_instruction(instruction)

    assert intent.interpretation_ready is True
    assert "research_prospects" in intent.requested_outcomes
    assert "synthesize_research_report" in intent.requested_outcomes
    assert "update_crm" not in intent.requested_outcomes
    assert "persist_internal_crm" not in intent.requested_outcomes

    record = MissionCompositionService(db=None).compose(tenant_id="tenant", instruction=instruction)
    assert record.ready_to_start is True
    assert record.clarifications == []
    research = next(step for step in record.planned_steps if step.action_name == "web.research")
    assert research.compile_gap is None
    assert research.tool_input["relation_requirements"][0]["reference_company"] == "1DevTeam"
    assert [step.action_name for step in record.planned_steps] == [
        "web.research",
        "research.verify_public_candidates",
        "research.synthesize_report",
    ]


def test_website_research_to_linkedin_drafts_compiles_complete_non_publish_graph() -> None:
    instruction = (
        "Research the public website 1devteam.com and create exactly three distinct LinkedIn post drafts "
        "based only on verified website information. Include supporting source links. "
        "Save the posts as drafts for review; do not publish them."
    )

    intent = interpret_instruction(instruction)
    record = MissionCompositionService(db=None).compose(tenant_id="tenant", instruction=instruction)

    assert intent.interpretation_ready is True
    assert intent.requested_quantity == 3
    assert "prepare_social_drafts" in intent.requested_outcomes
    assert "publish_content" not in intent.requested_outcomes
    assert "gtm.social_publish" in intent.forbidden_actions
    assert record.ready_to_start is True
    assert record.clarifications == []
    assert intent.target_entities[0].type == "web_page"
    assert intent.target_entities[0].url == "1devteam.com"
    assert [step.action_name for step in record.planned_steps] == [
        "web.research",
        "research.verify_public_candidates",
        "research.synthesize_report",
        "gtm.social_draft",
    ]
    research_step = record.planned_steps[0]
    assert research_step.tool_input["company"] == "1devteam.com"
    assert research_step.tool_input["domain"] == "1devteam.com"
    assert research_step.tool_input["query"] == "1devteam.com official website"
    assert research_step.tool_input["fetch_public_page"] is True
    social_step = record.planned_steps[-1]
    assert social_step.depends_on == ["ability-research-synthesize_report"]
    assert social_step.input_bindings == [
        {
            "from_step": "ability-research-synthesize_report",
            "output_path": "$.research_report",
            "to_step": "ability-gtm-social_draft",
            "input_path": "$.input.context.upstream.research_report",
        }
    ]
    assert social_step.tool_input["context"]["review_only"] is True
    assert social_step.tool_input["context"]["draft_count"] == 3


def test_unsupported_local_fixture_scope_is_a_compile_gap() -> None:
    record = MissionCompositionService(db=None).compose(
        tenant_id="tenant",
        instruction="Research three manufacturing companies in Chicago using local fixture data only.",
    )

    assert record.ready_to_start is False
    assert any(
        "local prospect fixtures require a configured industry/location scope" in (step.compile_gap or "")
        for step in record.planned_steps
    )


def test_supported_local_fixture_scopes_compile_without_public_search() -> None:
    record = MissionCompositionService(db=None).compose(
        tenant_id="tenant",
        instruction="Research three HVAC companies in Dallas using local fixture data only.",
    )

    assert record.ready_to_start is True
    research = next(step for step in record.planned_steps if step.action_name == "web.research")
    assert research.tool_input["local_fixture_only"] is True
    assert research.tool_input["include_public_search"] is False


def test_professional_services_fixture_scope_compiles_without_public_search() -> None:
    record = MissionCompositionService(db=None).compose(
        tenant_id="tenant",
        instruction="Research three professional services companies in Austin using local fixture data only.",
    )

    assert record.ready_to_start is True
    research = next(step for step in record.planned_steps if step.action_name == "web.research")
    assert research.tool_input["local_fixture_only"] is True
    assert research.tool_input["include_public_search"] is False


def test_declared_lattice_industries_compile_from_fixture_catalog() -> None:
    for industry in (
        "advertising",
        "electrical",
        "landscaping",
        "pest control",
        "legal",
        "dental",
        "recruiting",
        "SaaS",
        "e-commerce",
    ):
        record = MissionCompositionService(db=None).compose(
            tenant_id="tenant",
            instruction=f"Research three {industry} companies in Austin using local fixture data only.",
        )
        assert record.ready_to_start is True, industry
        research = next(step for step in record.planned_steps if step.action_name == "web.research")
        assert research.tool_input["local_fixture_only"] is True
        assert research.tool_input["include_public_search"] is False


def test_ajenda_internal_crm_source_disables_public_search() -> None:
    intent = interpret_instruction(
        "Research five software companies in Austin and summarize their matching Ajenda internal CRM records."
    )
    payload = build_action_input(action_name="web.research", intent=intent)
    assert payload["include_public_search"] is False
    assert payload["local_fixture_only"] is True


def test_local_fixture_constraint_lowers_qualification_threshold() -> None:
    intent = interpret_instruction(
        "Research five software companies in Austin and qualify the best three using local fixture data only."
    )
    payload = build_action_input(action_name="sales.qualify", intent=intent)

    assert payload["context"]["qualification_threshold_10"] == 5


def test_observed_public_research_uses_ranked_qualification_contract() -> None:
    intent = interpret_instruction(
        "Find 10 HVAC companies in Dallas, qualify the strongest three, and draft introductions. Do not send."
    )
    payload = build_action_input(action_name="sales.qualify", intent=intent)
    assert payload["context"]["requested_quantity"] == 3
    assert payload["context"]["qualification_threshold_10"] == 5


def test_evidence_ranking_does_not_require_contact_qualification() -> None:
    intent = interpret_instruction(
        "Find 10 HVAC companies in Dallas and rank them by evidence quality. Do not contact anyone."
    )
    payload = build_action_input(action_name="sales.qualify", intent=intent)

    assert payload["context"]["ranking_only"] is True


def test_local_fixture_constraint_propagates_to_contact_observation() -> None:
    intent = interpret_instruction(
        "Find five software companies in Austin and collect contacts using local fixture data only."
    )
    payload = build_action_input(action_name="research.observe_contacts", intent=intent)

    assert payload["local_fixture_only"] is True


def test_ajenda_internal_crm_source_propagates_to_contact_observation() -> None:
    intent = interpret_instruction("Qualify five software companies in Austin using Ajenda internal CRM records.")
    payload = build_action_input(action_name="research.observe_contacts", intent=intent)
    assert payload["local_fixture_only"] is True


def test_ajenda_internal_crm_source_uses_fixture_qualification_threshold() -> None:
    intent = interpret_instruction("Qualify five software companies in Austin using Ajenda internal CRM records.")
    payload = build_action_input(action_name="sales.qualify", intent=intent)
    assert payload["context"]["qualification_threshold_10"] == 5


def test_generic_internal_crm_source_uses_fixture_qualification_threshold() -> None:
    intent = interpret_instruction("Find three HVAC companies in Dallas from internal CRM and qualify them.")
    payload = build_action_input(action_name="sales.qualify", intent=intent)
    assert payload["context"]["qualification_threshold_10"] == 5


def test_browser_session_input_requires_explicit_target_url() -> None:
    intent = MissionIntent(
        objective="Read the target website",
        target_entities=[TargetEntity(type="company", url="https://example.com")],
    )

    payload = build_action_input(action_name="web.browser_session", intent=intent)

    assert payload == {
        "url": "https://example.com",
        "timeout_seconds": 15.0,
        "allowed_origins": ["https://example.com"],
        "commands": [{"action": "observe"}],
        "observation_requirements": [{"kind": "title"}, {"kind": "body"}],
    }


def test_browser_session_compiles_follow_link_as_bounded_click() -> None:
    intent = interpret_instruction(
        "Open https://example.com, follow its “More information…” link, and return the final URL, page title, visible text, and browser step trace."
    )
    payload = build_action_input(action_name="web.browser_session", intent=intent)
    assert intent.interpretation_ready is True
    assert intent.unmatched_material_clauses == []
    assert payload["commands"] == [
        {
            "action": "click",
            "selector": r'a:text-matches("^\\s*More\\ information\\s*(?:[….]*)?$", "i")',
        },
        {"action": "observe"},
    ]


def test_browser_session_compiles_explicit_selector_text_requirement() -> None:
    intent = interpret_instruction(
        'Observe https://example.com and extract text from CSS selector "h1". '
        "Return the title and extracted text. Do not send or modify anything."
    )
    payload = build_action_input(action_name="web.browser_session", intent=intent)

    assert payload["observation_requirements"] == [
        {"kind": "title"},
        {"kind": "body"},
        {"kind": "selector_text", "selector": "h1"},
    ]
    assert payload["commands"] == [
        {"action": "observe"},
        {"action": "extract", "selector": "h1"},
    ]


def test_browser_session_compiles_explicit_bounded_navigation() -> None:
    intent = interpret_instruction(
        "Open https://www.iana.org/domains/example, navigate to https://www.iana.org/domains, "
        "and return the final page title and final URL."
    )
    payload = build_action_input(action_name="web.browser_session", intent=intent)

    assert intent.interpretation_ready is True
    assert intent.unmatched_material_clauses == []
    assert payload["commands"] == [
        {"action": "navigate", "url": "https://www.iana.org/domains"},
        {"action": "observe"},
    ]


def test_public_identity_compiles_explicit_labeled_expectations() -> None:
    intent = interpret_instruction(
        "Verify the public identity of Acme HVAC at https://acmehvac.example. "
        "Expected company: Acme HVAC. Industry: HVAC. Location: Dallas. "
        "Return identity status and identity evidence URLs."
    )

    payload = build_action_input(action_name="research.verify_public_identity", intent=intent)

    assert payload == {
        "url": "https://acmehvac.example",
        "expected_company": "Acme HVAC",
        "industry": "HVAC",
        "location": "Dallas",
        "timeout_seconds": 15.0,
    }
