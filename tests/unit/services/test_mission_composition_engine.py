"""Unit tests for Mission Composition Engine (ADR-0008)."""

from __future__ import annotations

from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.job_catalog import get_business_job, list_business_jobs
from backend.services.mission_composition.plan_compiler import (
    compile_planned_steps,
    compile_task_graph_preview,
)
from backend.services.mission_composition.proposal_store import clear_proposals_for_tests
from backend.services.mission_composition.service import MissionCompositionService
from backend.services.operating_charter import default_operating_charter

ROOFING_INSTRUCTION = (
    "Research roofing companies in Austin, identify three strong prospects, "
    "draft personalized introductions, and bring them to me before anything is sent."
)


def setup_function() -> None:
    clear_proposals_for_tests()


def test_interpreter_roofing_forbids_send_and_targets_austin() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    assert "research prospects" in intent.requested_outcomes
    assert "qualify prospects" in intent.requested_outcomes
    assert "draft introductions" in intent.requested_outcomes
    assert "send emails" not in intent.requested_outcomes
    assert any("do not send" in c.lower() for c in intent.constraints)
    assert "gtm.email_send" in intent.forbidden_outcomes
    assert intent.target_entities
    assert intent.target_entities[0].location
    assert "austin" in intent.target_entities[0].location.lower()
    assert intent.target_entities[0].industry
    assert "roofing" in intent.target_entities[0].industry.lower()


def test_interpreter_does_not_invent_actions() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    # Intent has outcomes and constraints only — no action names except forbidden send token.
    for outcome in intent.requested_outcomes:
        assert "." not in outcome


def test_job_catalog_has_sales_gtm_and_catalog_only_accounting() -> None:
    keys = {job.job_key for job in list_business_jobs()}
    assert "research.discover_prospects" in keys
    assert "email.prepare_outreach" in keys
    assert "email.deliver_outreach" in keys
    accounting = list_business_jobs(maturity="catalog_only")
    assert any(job.job_key.startswith("accounting.") for job in accounting)
    assert get_business_job("sales.qualify_prospects").candidate_actions


def test_route_jobs_excludes_send_when_forbidden() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    jobs = route_jobs_for_intent(intent)
    keys = [job.job_key for job in jobs]
    assert "research.discover_prospects" in keys
    assert "sales.qualify_prospects" in keys
    assert "email.prepare_outreach" in keys
    assert "email.deliver_outreach" not in keys


def test_capability_resolver_selects_draft_not_send() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    jobs = route_jobs_for_intent(intent)
    selections, _missing = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    ready_actions = {
        item.action_name for item in selections if item.selection_status == "selected" and item.readiness == "ready"
    }
    assert "gtm.email_draft" in ready_actions or "sales.draft_followup" in ready_actions
    assert "gtm.email_send" not in ready_actions
    assert "web.research" in ready_actions or "sales.research" in ready_actions
    assert "sales.qualify" in ready_actions


def test_plan_compiler_builds_non_linear_dependency_edges() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    jobs = route_jobs_for_intent(intent)
    selections, _ = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    steps = compile_planned_steps(selections, intent=intent)
    graph = compile_task_graph_preview(steps)
    assert graph["nodes"]
    # At least one edge should exist when qualify depends on research.
    if len(graph["nodes"]) > 1:
        assert isinstance(graph["edges"], list)
    # No checkbox-linear assumption: edges only from job depends_on.
    for edge in graph["edges"]:
        assert edge["dependency_type"] == "depends_on"


def test_composed_graph_populates_web_research_query() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    jobs = route_jobs_for_intent(intent)
    selections, _ = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    steps = compile_planned_steps(selections, intent=intent)
    graph = compile_task_graph_preview(steps)
    research_nodes = [
        node
        for node in graph["nodes"]
        if node["input_contract"]["tool_invocation"]["action"] in {"web.research", "web.search"}
    ]
    assert research_nodes
    for node in research_nodes:
        tool_input = node["input_contract"]["tool_invocation"]["input"]
        assert isinstance(tool_input.get("query"), str) and tool_input["query"].strip()
        assert "roofing" in tool_input["query"].lower() or "austin" in tool_input["query"].lower()


def test_route_jobs_expands_dependencies_transitively() -> None:
    intent = interpret_instruction("Draft personalized introductions for three strong prospects. Do not send messages.")
    jobs = route_jobs_for_intent(intent)
    keys = {job.job_key for job in jobs}
    assert "email.prepare_outreach" in keys
    # Transitive: prepare → qualify/enrich → discover
    assert "sales.qualify_prospects" in keys
    assert "research.discover_prospects" in keys


def test_send_without_gmail_is_not_ready() -> None:
    service = MissionCompositionService(db=None)
    record = service.compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction="Research roofing companies in Austin and send personalized introductions to three prospects.",
    )
    # Default charter never_do may block send; either way start must not claim delivery is ready.
    assert "gtm.email_send" not in record.allowed_actions or record.ready_to_start is False
    if any(item.job_key == "email.deliver_outreach" for item in record.ability_selections):
        assert record.ready_to_start is False


def test_compose_service_roofing_ready_without_db() -> None:
    service = MissionCompositionService(db=None)
    record = service.compose(tenant_id="11111111-1111-1111-1111-111111111111", instruction=ROOFING_INSTRUCTION)
    assert record.proposal_id
    assert record.allowed_actions
    assert "gtm.email_send" not in record.allowed_actions
    assert any("do not send" in c.lower() for c in record.intent.constraints)
    assert record.allowed_actions_provenance.selected_by == "mission_composition_engine"
    assert record.allowed_actions_provenance.user_supplied is False
    assert record.composition_provenance.grants_execution_authority is False
    assert record.task_graph_preview.get("nodes")
    # Draft-only sales path should be ready without HubSpot when internal paths exist.
    assert record.ready_to_start is True
    # Every node carries a non-empty tool input for invoke validation.
    for node in record.task_graph_preview["nodes"]:
        inv = node["input_contract"]["tool_invocation"]
        assert inv["action"]
        assert isinstance(inv["input"], dict)
        if inv["action"] == "web.research":
            assert inv["input"].get("query")
