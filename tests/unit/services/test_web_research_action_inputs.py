"""Entity-first web.research inputs for composition graphs."""

from __future__ import annotations

from backend.services.mission_composition.action_inputs import build_action_input
from backend.services.mission_composition.intent_interpreter import interpret_instruction


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
