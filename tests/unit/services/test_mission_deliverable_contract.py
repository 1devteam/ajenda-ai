from __future__ import annotations

from backend.services.mission_composition import deliverable_contract
from backend.services.mission_composition.intent_interpreter import interpret_instruction


def test_extracts_live_saas_deliverable_fields_and_score_range() -> None:
    instruction = (
        "Find 10 SaaS companies in Austin, Texas that could be good prospects for Ajenda AI. "
        "Research and qualify each company based on what it sells, whether it uses AI or automated software, "
        "and whether Ajenda AI could help the company manage those systems safely and consistently. "
        "For each prospect, provide the company name, website, a short description of what it sells, "
        "the evidence used to qualify it, why Ajenda AI may be relevant, and a qualification score from 1 to 5."
    )

    request = deliverable_contract.extract_deliverable_request(instruction)

    assert request is not None
    assert request.scope == "per_prospect"
    assert [field.field_key for field in request.fields] == [
        "company_name",
        "website",
        "product_description",
        "qualification_evidence",
        "ajenda_relevance",
        "qualification_score",
    ]
    assert request.score_min == 1
    assert request.score_max == 5
    assert request.fully_understood
    assert request.grants_execution_authority is False


def test_extracts_long_context_return_contract_without_silent_drops() -> None:
    instruction = (
        "Research six candidates and qualify the best three. "
        "Return the research, qualification reasons, sources, drafts, assumptions, and limitations for review."
    )

    request = deliverable_contract.extract_deliverable_request(instruction)

    assert request is not None
    assert request.scope == "mission"
    assert [field.field_key for field in request.fields] == [
        "research_summary",
        "qualification_reasons",
        "sources",
        "drafts",
        "assumptions",
        "limitations",
    ]
    assert request.unresolved_items == ()
    assert request.fully_understood


def test_unknown_deliverable_items_remain_explicitly_unresolved() -> None:
    request = deliverable_contract.extract_deliverable_request(
        "For each prospect, provide the company name, website, and lunar risk index."
    )

    assert request is not None
    assert [field.field_key for field in request.fields] == ["company_name", "website"]
    assert request.unresolved_items == ("lunar risk index",)
    assert not request.fully_understood


def test_descriptive_conjunctions_are_not_misread_as_deliverables() -> None:
    request = deliverable_contract.extract_deliverable_request(
        "Qualify each company based on whether it manages AI systems safely and consistently."
    )

    assert request is None


def test_browser_observation_fields_do_not_become_prospect_website() -> None:
    request = deliverable_contract.extract_deliverable_request(
        "Open https://www.iana.org/domains/example and return the final URL, page title, visible text, observation timestamp, browser step trace, and blocked-request list."
    )

    assert request is not None
    assert [field.field_key for field in request.fields] == [
        "final_url",
        "title",
        "extracted_observations",
        "observation_timestamp",
        "browser_trace",
        "blocked_requests",
    ]
    assert request.unresolved_items == ()
    assert request.fully_understood


def test_browser_observation_does_not_fuzzy_match_contact_observation() -> None:
    intent = interpret_instruction(
        "Open https://www.iana.org/domains/example, follow its Domains link, and return the final URL, page title, visible text, and browser step trace."
    )

    assert intent.requested_outcomes == ["observe_web_page"]


def test_public_identity_fields_are_typed_deliverable_fields() -> None:
    request = deliverable_contract.extract_deliverable_request(
        "Verify https://acmehvac.example as Acme HVAC in Dallas HVAC and return the identity status, identity evidence URLs, identity match reasons, and identity gaps."
    )

    assert request is not None
    assert [field.field_key for field in request.fields] == [
        "identity_status",
        "identity_evidence_urls",
        "identity_match_reasons",
        "identity_gaps",
    ]
    assert request.unresolved_items == ()
