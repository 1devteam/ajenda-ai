"""Unit tests for Mission Composition Engine (ADR-0008)."""

from __future__ import annotations

from backend.services.mission_composition.action_inputs import build_action_input
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
    assert "research_prospects" in intent.requested_outcomes
    assert "qualify_prospects" in intent.requested_outcomes
    assert "prepare_outreach" in intent.requested_outcomes
    assert "send_outreach" not in intent.requested_outcomes
    assert intent.send_policy.mode == "forbid"
    assert intent.blocks_send()
    assert "gtm.email_send" in intent.forbidden_outcomes
    assert intent.requested_quantity == 3
    assert intent.quantity_provenance == "explicit"
    assert intent.target_entities
    assert intent.target_entities[0].location
    assert intent.target_entities[0].location.lower() == "austin"
    assert intent.target_entities[0].industry
    assert intent.target_entities[0].industry.lower() == "roofing"
    assert "research" not in intent.target_entities[0].industry.lower()
    assert "identify" not in intent.target_entities[0].location.lower()


def test_interpreter_stops_location_before_trailing_verbs() -> None:
    intent = interpret_instruction("research roofing companies in fayetteville AR identify three strong competors")
    assert intent.target_entities
    assert intent.target_entities[0].industry.lower() == "roofing"
    assert intent.target_entities[0].location.lower() == "fayetteville ar"
    assert "identify" not in intent.target_entities[0].location.lower()
    assert "research_prospects" in intent.requested_outcomes


def test_interpreter_emits_canonical_outcome_ids_only() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    for outcome in intent.requested_outcomes:
        assert " " not in outcome
        assert outcome.replace("_", "").isalnum()


def test_job_catalog_routes_canonical_ids_only() -> None:
    keys = {job.job_key for job in list_business_jobs()}
    assert "research.discover_prospects" in keys
    assert "email.prepare_outreach" in keys
    assert "email.deliver_outreach" in keys
    for job in list_business_jobs(maturity="runtime_bound"):
        for outcome in job.supported_outcomes:
            assert " " not in outcome
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
    if len(graph["nodes"]) > 1:
        assert isinstance(graph["edges"], list)
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
        assert tool_input.get("limit") == 3


def test_action_inputs_use_structured_quantity_not_prose() -> None:
    intent = interpret_instruction(
        "Research five roofing companies in Austin and draft personalized introductions. Do not send."
    )
    assert intent.requested_quantity == 5
    payload = build_action_input(action_name="web.research", intent=intent)
    assert payload["limit"] == 5
    # Success criteria may mention five, but count source is structured field.
    intent.success_criteria[0].description = "ignore this prose with ten prospects"
    payload2 = build_action_input(action_name="web.research", intent=intent)
    assert payload2["limit"] == 5


def test_route_jobs_expands_dependencies_transitively() -> None:
    intent = interpret_instruction("Draft personalized introductions for three strong prospects. Do not send messages.")
    jobs = route_jobs_for_intent(intent)
    keys = {job.job_key for job in jobs}
    assert "email.prepare_outreach" in keys
    assert "sales.qualify_prospects" in keys
    assert "research.discover_prospects" in keys


def test_send_without_gmail_is_not_ready() -> None:
    service = MissionCompositionService(db=None)
    record = service.compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction="Research roofing companies in Austin and send personalized introductions to three prospects.",
    )
    assert "gtm.email_send" not in record.allowed_actions or record.ready_to_start is False
    if any(item.job_key == "email.deliver_outreach" for item in record.ability_selections):
        assert record.ready_to_start is False


def test_calendar_briefing_instruction_routes_to_calendar_job() -> None:
    intent = interpret_instruction(
        "Provide a calendar briefing: read calendar for upcoming commitments and prepare meeting briefs."
    )
    assert "read_calendar" in intent.requested_outcomes
    jobs = route_jobs_for_intent(intent)
    assert any(job.job_key == "ops.calendar_briefing" for job in jobs)
    assert intent.ambiguity == [] or not any(c.field == "success_criteria" for c in intent.ambiguity)
    assert any(c.measurable for c in intent.success_criteria)


def test_known_job_completion_contract_skips_success_criteria_restatement() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    assert not any(item.field == "success_criteria" for item in intent.ambiguity)
    assert all(c.measurable for c in intent.success_criteria)


def test_fragment_answer_does_not_become_executable_mission() -> None:
    intent = interpret_instruction("Complete when the email is sent.")
    assert intent.requested_outcomes == []
    assert intent.ambiguity
    text = " ".join(item.question for item in intent.ambiguity).lower()
    assert "restate the complete mission" in text
    assert "what concrete deliverables" not in text
    assert "what business outcomes" not in text

    service = MissionCompositionService(db=None)
    record = service.compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction="Complete when the email is sent.",
    )
    assert record.ready_to_start is False
    assert record.clarifications
    joined = " ".join(c.question for c in record.clarifications).lower()
    assert "restate the complete mission" in joined
    again = service.compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction="Five companies.",
    )
    assert again.ready_to_start is False
    assert again.clarifications
    again_text = " ".join(c.question for c in again.clarifications).lower()
    assert "restate the complete mission" in again_text
    assert "what concrete deliverables" not in again_text


def test_send_only_instruction_uses_send_completion_contract() -> None:
    intent = interpret_instruction("Send a follow-up email to a prospect.")
    assert "send_outreach" in intent.requested_outcomes
    assert intent.send_policy.mode == "allow"
    assert not any(item.field == "success_criteria" for item in intent.ambiguity)
    assert any(
        "accepted-send" in c.description.lower() or "message identifier" in c.description.lower()
        for c in intent.success_criteria
    )


def test_send_after_approval_is_conditional_not_immediate_send_job() -> None:
    intent = interpret_instruction("Draft and send the emails, but do not send anything until I approve it.")
    assert "prepare_outreach" in intent.requested_outcomes
    assert "send_outreach" not in intent.requested_outcomes
    assert intent.send_policy.mode == "conditional"
    assert intent.send_policy.condition == "approval"
    jobs = route_jobs_for_intent(intent)
    assert "email.deliver_outreach" not in {job.job_key for job in jobs}


def test_unmatched_material_clause_fails_closed() -> None:
    intent = interpret_instruction(
        "Research three roofing companies in Austin, qualify them, draft emails, "
        "and post the results on LinkedIn without my approval."
    )
    assert "research_prospects" in intent.requested_outcomes
    assert "publish_content" in intent.requested_outcomes
    assert intent.ambiguity
    assert any("restate the complete mission" in c.question.lower() for c in intent.ambiguity)


def test_hubspot_named_as_source_does_not_route_crm_write() -> None:
    intent = interpret_instruction("Research five roofing companies in Austin from HubSpot CRM records.")
    assert "research_prospects" in intent.requested_outcomes
    assert "update_crm" not in intent.requested_outcomes


def test_linkedin_as_research_source_does_not_require_publish() -> None:
    intent = interpret_instruction("Find five prospects on LinkedIn in Austin roofing market.")
    assert "research_prospects" in intent.requested_outcomes
    assert "publish_content" not in intent.requested_outcomes


def test_enrich_not_invented_from_draft_and_qualify() -> None:
    intent = interpret_instruction("Identify three strong prospects and draft personalized introductions. Do not send.")
    assert "qualify_prospects" in intent.requested_outcomes or "research_prospects" in intent.requested_outcomes
    assert "prepare_outreach" in intent.requested_outcomes
    assert "enrich_contacts" not in intent.requested_outcomes


def test_credential_reference_is_copied_into_graph_input_contract() -> None:
    from backend.services.mission_composition.contracts import AbilitySelection

    selection = AbilitySelection(
        job_key="email.deliver_outreach",
        ability_id="gtm-email-send",
        action_name="gtm.email_send",
        selection_status="selected",
        selection_reason="connected gmail",
        readiness="ready",
        vertical_role="vertical.email",
        side_effect_class="external_send",
        credential_reference={
            "schema_version": 1,
            "credential_id": "gmail-email",
            "provider": "external_email",
            "credential_type": "api_key",
        },
    )
    intent = interpret_instruction("Send a follow-up email to a prospect.")
    steps = compile_planned_steps([selection], intent=intent)
    graph = compile_task_graph_preview(steps, selections=[selection], approved_by="tester")
    node = graph["nodes"][0]
    cred = node["input_contract"].get("credential_reference")
    assert cred is not None
