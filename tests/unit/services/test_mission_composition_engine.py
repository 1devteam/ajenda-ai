"""Unit tests for Mission Composition Engine (ADR-0008)."""

from __future__ import annotations

import pytest

from backend.services.mission_composition.action_inputs import build_action_input
from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.interpretation.normalize import normalize_instruction_text
from backend.services.mission_composition.job_catalog import get_business_job, list_business_jobs
from backend.services.mission_composition.plan_compiler import (
    compile_planned_steps,
    compile_task_graph_preview,
)
from backend.services.mission_composition.proposal_store import clear_proposals_for_tests
from backend.services.mission_composition.service import (
    MissionCompositionService,
    _profile_context,
)
from backend.services.mission_composition.structured_planner import (
    PlannerBudgetProposal,
    PlannerJobProposal,
    PlannerResult,
    StructuredPlannerProposal,
)
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


def test_business_income_review_compiles_profile_dependency_and_report() -> None:
    intent = interpret_instruction("Review my business and suggest possible ways to increase income.")
    assert intent.interpretation_ready
    assert intent.requested_outcomes == ["review_business_income"]

    jobs = route_jobs_for_intent(intent)
    assert [job.job_key for job in jobs] == [
        "intelligence.retrieve_business_profile",
        "business.review_income",
    ]
    selections, missing = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    assert missing == []
    planned = compile_planned_steps(selections, intent=intent)
    review = planned[-1]
    assert review.output_contract == "business_review_report"
    assert review.input_bindings[0]["output_path"] == "$.business_profile_facts"
    assert review.input_bindings[0]["input_path"] == "$.input.context.business_profile_facts"
    assert planned[0].tool_input["query"].startswith("Ajenda products services")


def test_business_income_review_accepts_explicit_evidence_clauses() -> None:
    intent = interpret_instruction(
        "Review my business and suggest possible ways to increase income. "
        "Use only the approved business profile; identify three evidence-limited opportunities; "
        "list the evidence gaps."
    )
    assert intent.interpretation_ready
    assert intent.requested_outcomes == ["review_business_income"]
    assert intent.unmatched_material_clauses == []


def test_interpreter_preserves_software_rnd_target_and_profile_context() -> None:
    instruction = (
        "Use 1DevTeam's approved business profile to research software and R&D developer companies in Austin, "
        "qualify prospects, and prepare drafts without sending messages."
    )
    intent = interpret_instruction(instruction, profile_context={"company": "1DevTeam", "product": "Ajenda-AI"})
    assert intent.interpretation_ready
    assert intent.target_entities
    assert intent.target_entities[0].industry.lower() == "software and r&d developer"
    assert intent.target_entities[0].location.lower() == "austin"
    assert "business_profile" in intent.context_requirements
    assert not intent.unmatched_material_clauses


def test_interpreter_maps_approved_prospect_save_to_crm_write() -> None:
    intent = interpret_instruction(
        "Research software companies in Austin, qualify prospects, and save only approved prospects to the CRM."
    )
    assert "update_crm" in intent.requested_outcomes


def test_interpreter_accounts_sourced_comparison_as_research_deliverable() -> None:
    intent = interpret_instruction(
        "Find five software companies in Austin. Produce a sourced comparison and identify evidence gaps."
    )

    assert intent.interpretation_ready
    assert "synthesize_research_report" in intent.requested_outcomes
    assert intent.unmatched_material_clauses == []


def test_interpreter_routes_governed_ajenda_profile_brief_to_internal_memory_only() -> None:
    instruction = (
        "Search Ajenda's approved business profile and governed internal memory. "
        "Produce an evidence-backed brief explaining who Ajenda is, its products and services, "
        "target customers, and key differentiators. Identify missing or conflicting facts without guessing. "
        "Do not browse the web, contact anyone, send email, modify CRM records, or perform any external action."
    )
    intent = interpret_instruction(instruction)
    assert intent.interpretation_ready
    assert intent.requested_outcomes == ["read_business_profile"]
    assert intent.send_policy.mode == "forbid"
    assert "gtm.email_send" in intent.forbidden_actions
    assert not intent.unmatched_material_clauses

    jobs = route_jobs_for_intent(intent)
    assert [job.job_key for job in jobs] == ["intelligence.retrieve_business_profile"]
    selections, missing = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    assert not missing
    assert [(item.action_name, item.readiness) for item in selections] == [("retrieval.hybrid_search", "ready")]
    planned = compile_planned_steps(selections, intent=intent)
    assert planned[0].tool_input["query"].startswith("Ajenda products services")


def test_profile_context_preserves_the_full_approved_business_vocabulary() -> None:
    class Profile:
        id = "profile-1"
        approved_facts = {
            "business_name": {"value": "Ajenda AI"},
            "industry": {"value": "AI operations"},
            "description": {"value": "Governed AI operations"},
            "products_services": ["Mission execution", "CRM research"],
            "target_customers": ["Operator-led teams"],
            "differentiators": ["Evidence-backed runtime"],
            "operator_notes": {"value": "Do not guess"},
        }
        provenance = {}

    context = _profile_context(Profile())
    assert context["business_name"] == "Ajenda AI"
    assert context["industry"] == "AI operations"
    assert context["description"] == "Governed AI operations"
    assert context["target_customers"] == ["Operator-led teams"]
    assert context["differentiators"] == ["Evidence-backed runtime"]
    assert context["operator_notes"] == "Do not guess"


def test_composition_projects_replayable_intelligence_envelope_without_authority() -> None:
    record = MissionCompositionService(db=None).compose(
        tenant_id="tenant-v2",
        instruction=ROOFING_INSTRUCTION,
    )
    envelope = record.intelligence_envelope
    assert envelope is not None
    assert envelope.tenant_id == "tenant-v2"
    assert envelope.requested_outcomes == tuple(record.intent.requested_outcomes)
    assert envelope.material_clause_ids
    assert envelope.named_job_keys
    assert envelope.planned_step_keys == tuple(step.step_key for step in record.planned_steps)
    assert envelope.authority_class == "read_model"
    assert not any(gap.blocking for gap in envelope.layer_gaps)
    assert record.composition_provenance.grants_execution_authority is False
    assert record.ready_to_start is True


def test_negated_crm_records_are_not_misread_as_hubspot_read() -> None:
    intent = interpret_instruction("Read Ajenda's approved business profile. Do not modify CRM records or send email.")
    assert "read_crm" not in intent.requested_outcomes
    assert "read_business_profile" in intent.requested_outcomes
    assert intent.send_policy.mode == "forbid"


def test_negated_contact_anyone_does_not_route_contacts_vocabulary() -> None:
    intent = interpret_instruction(
        "Research five competitors of Ajenda AI and produce a comparison report. "
        "Do not contact anyone, modify external systems, or publish content."
    )

    assert "read_contacts" not in intent.requested_outcomes


def test_negated_connector_read_does_not_authorize_read_or_fuzzy_email() -> None:
    intent = interpret_instruction("Do not read CRM records. Send the approved email now.")
    assert intent.requested_outcomes == ["send_outreach"]
    assert "read_crm" not in intent.requested_outcomes
    assert "read_email" not in intent.requested_outcomes


def test_detailed_report_deliverable_materializes_synthesis_node() -> None:
    intent = interpret_instruction(
        "Research five competitors of Ajenda AI. Produce a comparison table, highlight three opportunities, "
        "and identify evidence gaps."
    )

    assert intent.interpretation_ready
    assert "synthesize_research_report" in intent.requested_outcomes

    record = MissionCompositionService(db=None).compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction=intent.raw_instruction,
    )
    synthesis = next(
        node
        for node in record.task_graph_preview["nodes"]
        if node["metadata"]["action"] == "research.synthesize_report"
    )
    assert synthesis["output_contract"] == {"artifact": "research_report"}
    assert synthesis["input_contract"]["tool_invocation"]["input"]["binding_required"] is True
    assert synthesis["metadata"]["input_bindings"] == [
        {
            "from_step": "ability-web-research",
            "output_path": "$.prospect_candidates",
            "to_step": "ability-research-synthesize_report",
            "input_path": "$.input.prospects",
        }
    ]
    assert record.task_graph_preview["edges"]
    assert record.composition_provenance.know_how_id == "revops.gtm-crm-communications"
    assert record.composition_provenance.know_how_version == "2.0.0"
    assert record.composition_provenance.grants_execution_authority is False


def test_long_objective_is_preserved_without_lossy_truncation() -> None:
    instruction = "Research competitors and provide evidence. " + "Include verified details. " * 30
    intent = interpret_instruction(instruction)

    assert intent.objective == normalize_instruction_text(instruction).normalized
    assert not intent.objective.endswith("...")


def test_send_contradiction_across_sentences_fails_closed() -> None:
    intent = interpret_instruction("Do not send email. Send the approved email now.")
    assert not intent.requested_outcomes
    assert intent.contradictions
    assert any(item.field == "send_policy" for item in intent.ambiguity)


def test_revops_composition_is_pinned_to_selected_know_how_version() -> None:
    service = MissionCompositionService(db=None)
    record = service.compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction=ROOFING_INSTRUCTION,
    )
    assert record.composition_provenance.know_how_id == "revops.research-to-approved-outreach"
    assert record.composition_provenance.know_how_version == "1.0.0"


def test_unrepresentable_action_scope_returns_named_work_with_planner_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_scope(*_args: object, **_kwargs: object) -> list[object]:
        raise ValueError("CRM filter cannot be represented by company search")

    monkeypatch.setattr("backend.services.mission_composition.service.compile_planned_steps", reject_scope)
    record = MissionCompositionService(db=None).compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction="Read HubSpot company records for roofing prospects.",
    )
    assert record.ready_to_start is False
    envelope = record.intelligence_envelope
    assert envelope is not None
    planner_gaps = [gap for gap in envelope.layer_gaps if gap.layer == "planner" and gap.blocking]
    assert planner_gaps
    assert any("cannot be represented" in gap.message for gap in planner_gaps)
    assert envelope.named_job_keys or record.ability_selections


def test_valid_injected_structured_planner_is_persisted_as_non_authoritative_proposal() -> None:
    class Planner:
        def propose(self, request: object) -> PlannerResult:
            clause_ids = tuple(item["clause_id"] for item in request.material_clauses)  # type: ignore[attr-defined]
            job_keys = (
                "research.discover_prospects",
                "research.observe_sources",
                "sales.qualify_prospects",
                "gtm.enrich_contacts",
                "email.prepare_outreach",
            )
            return PlannerResult(
                proposal=StructuredPlannerProposal(
                    objective="Research, qualify, and draft without sending.",
                    know_how_id=request.know_how_id,  # type: ignore[attr-defined]
                    know_how_version=request.know_how_version,  # type: ignore[attr-defined]
                    material_clause_ids=clause_ids,
                    jobs=tuple(PlannerJobProposal(job_key=key, reason="Required by instruction.") for key in job_keys),
                    success_criteria=("Drafts are ready for review.",),
                    budget=PlannerBudgetProposal(
                        max_steps=10,
                        max_replans=1,
                        max_provider_calls=10,
                        max_model_tokens=10_000,
                        max_wall_seconds=300,
                        max_cost_usd=5,
                    ),
                ),
                provider="test_planner",
                model="test-model",
            )

    record = MissionCompositionService(db=None, planner_provider=Planner()).compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction=ROOFING_INSTRUCTION,
    )
    assert record.planner_proposal is not None
    assert record.planner_proposal["grants_execution_authority"] is False
    assert record.planner_provenance is not None
    assert record.planner_provenance["status"] == "validated_proposal"


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
    accounting = {
        job.job_key for job in list_business_jobs(maturity="runtime_bound") if job.job_key.startswith("accounting.")
    }
    assert {
        "accounting.read_revenue",
        "accounting.prepare_reconciliation",
        "accounting.prepare_invoice_drafts",
    } <= accounting
    assert get_business_job("sales.qualify_prospects").candidate_actions


def test_route_jobs_excludes_send_when_forbidden() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    jobs = route_jobs_for_intent(intent)
    keys = [job.job_key for job in jobs]
    assert "research.discover_prospects" in keys
    assert "sales.qualify_prospects" in keys
    assert "email.prepare_outreach" in keys
    assert "email.deliver_outreach" not in keys


def test_public_discovery_always_routes_through_identity_observation() -> None:
    intent = interpret_instruction("Find 10 HVAC companies in Dallas")
    keys = {job.job_key for job in route_jobs_for_intent(intent)}

    assert "research.discover_prospects" in keys
    assert "research.observe_sources" in keys
    assert "sales.qualify_prospects" not in keys


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
    for node in graph["nodes"]:
        assert node["output_contract"] == {"artifact": node["metadata"]["output_contract"]}


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


def test_find_companies_names_research_and_holds_target_scope_without_fake_query() -> None:
    record = MissionCompositionService(db=None).compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction="Find companies",
    )
    envelope = record.intelligence_envelope
    assert envelope is not None
    assert "research.discover_prospects" in envelope.named_job_keys
    assert record.proposal_status != "interpretation_failed"
    assert record.proposal_status == "gaps_open"
    assert record.ready_to_start is False
    layers = {gap.layer for gap in envelope.layer_gaps if gap.blocking}
    assert "interpreter" in layers
    assert "algorithm" in layers or "planner" in layers
    assert any(gap.field == "target_scope" and gap.layer == "interpreter" for gap in envelope.layer_gaps)
    assert any(
        gap.blocking and gap.layer in {"algorithm", "planner"} and gap.field in {"target_scope", "planned_steps"}
        for gap in envelope.layer_gaps
    )
    assert "web.research" not in record.allowed_actions
    for step in record.planned_steps:
        assert step.tool_input.get("query") != "companies"
        assert step.compile_gap or step.action_name != "web.research"


def test_github_read_without_owner_repo_reports_algorithm_gap_not_placeholder() -> None:
    record = MissionCompositionService(db=None).compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction="Read my GitHub repository.",
    )
    assert record.ready_to_start is False
    envelope = record.intelligence_envelope
    assert envelope is not None
    assert any(gap.field == "github_owner_repo" or gap.code == "unbound_required_input" for gap in envelope.layer_gaps)
    for step in record.planned_steps:
        if step.action_name == "github.repo_read":
            assert step.tool_input.get("owner") != "pending"
            assert step.tool_input.get("repo") != "pending"
            assert step.compile_gap


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
    envelope = record.intelligence_envelope
    assert envelope is not None
    layers = {gap.layer for gap in envelope.layer_gaps if gap.blocking}
    assert layers == {"interpreter", "algorithm", "planner"}


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


def test_forbid_email_sending_is_not_parsed_as_send_authority() -> None:
    intent = interpret_instruction("Review the approved business profile and forbid email sending and CRM updates.")
    assert intent.send_policy.mode == "forbid"
    assert "send_outreach" not in intent.requested_outcomes
    assert "gtm.email_send" in intent.forbidden_actions


def test_publish_content_is_runtime_bound_not_stranded() -> None:
    intent = interpret_instruction(
        "Research three roofing companies in Austin, qualify them, draft emails, "
        "and post the results on LinkedIn without my approval. Do not send emails."
    )
    assert "research_prospects" in intent.requested_outcomes
    assert "publish_content" in intent.requested_outcomes
    assert intent.success_criteria
    assert any("publish" in c.description.lower() for c in intent.success_criteria)
    jobs = route_jobs_for_intent(intent)
    assert "gtm.publish_content" in {job.job_key for job in jobs}


def test_unmatched_material_clause_fails_closed() -> None:
    intent = interpret_instruction(
        "Research three roofing companies in Austin and fax each of them a signed purchase order"
    )
    assert "research_prospects" in intent.requested_outcomes
    # "fax … purchase order" is material without a canonical outcome mapping.
    assert intent.unmatched_material_clauses or any(c.field == "clause_coverage" for c in intent.ambiguity)
    assert intent.ambiguity
    assert any("restate the complete mission" in c.question.lower() for c in intent.ambiguity)


def test_hubspot_named_as_source_does_not_route_crm_write() -> None:
    intent = interpret_instruction("Research five roofing companies in Austin from HubSpot CRM records.")
    assert "research_prospects" in intent.requested_outcomes
    assert "update_crm" not in intent.requested_outcomes


def test_research_with_internal_crm_summary_is_a_valid_read_mission() -> None:
    intent = interpret_instruction(
        "Research five software development companies in Austin and summarize their matching Ajenda internal CRM records. "
        "Do not modify records or send messages."
    )
    assert "research_prospects" in intent.requested_outcomes
    assert "update_crm" not in intent.requested_outcomes
    assert "hubspot_source" not in intent.context_requirements
    assert not intent.ambiguity


def test_internal_crm_review_routes_to_local_records_before_qualification() -> None:
    intent = interpret_instruction(
        "Review the five Austin software companies already saved in Ajenda's CRM, "
        "compare their qualification evidence and contact quality, rank them from strongest "
        "to weakest, recommend the next step for each, and prepare draft introduction emails "
        "for the top three contacts for my review, but do not send anything."
    )

    assert "read_crm" in intent.requested_outcomes
    assert "internal_crm_source" in intent.context_requirements
    jobs = route_jobs_for_intent(intent)
    assert "research.discover_prospects" not in {job.job_key for job in jobs}

    selections, missing = resolve_jobs(jobs, intent=intent)
    assert missing == []
    local_read = next(item for item in selections if item.job_key == "crm.read_records")
    assert local_read.action_name == "record.search"

    payload = build_action_input(action_name="record.search", intent=intent)
    assert payload["record_type"] == "account"
    assert payload["limit"] == 5


def test_internal_crm_review_with_negated_updates_stays_local() -> None:
    intent = interpret_instruction(
        "Review the five software development companies already saved in Ajenda\u2019s internal CRM. "
        "Compare their qualification evidence and contact quality, rank them from strongest to weakest, "
        "and recommend the next step for each. Use Ajenda\u2019s internal records only; do not search the web, "
        "use HubSpot, modify CRM records, or send messages."
    )

    assert "read_crm" in intent.requested_outcomes
    assert "internal_crm_source" in intent.context_requirements
    jobs = route_jobs_for_intent(intent)
    assert "research.discover_prospects" not in {job.job_key for job in jobs}
    selections, missing = resolve_jobs(jobs, intent=intent)
    assert missing == []
    local_read = next(item for item in selections if item.job_key == "crm.read_records")
    assert local_read.action_name == "record.search"


def test_internal_crm_gtm_review_binds_read_before_observe_qualify_and_draft() -> None:
    instruction = (
        "Review the five Austin software companies already saved in Ajenda's internal CRM, "
        "rank them by qualification evidence, recommend the next step for each, and prepare "
        "draft introduction emails for the top three for my review. Do not modify CRM records "
        "or send messages."
    )
    intent = interpret_instruction(instruction)
    jobs = route_jobs_for_intent(intent)
    selections, missing = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    assert missing == []

    steps = compile_planned_steps(selections, intent=intent)
    assert [step.action_name for step in steps] == [
        "record.search",
        "research.observe_contacts",
        "sales.qualify",
        "gtm.email_draft",
    ]
    observe = steps[1]
    assert observe.depends_on == ["ability-record-search"]
    assert {(binding["output_path"], binding["input_path"]) for binding in observe.input_bindings} == {
        ("$.crm_records", "$.input.prospects")
    }
    assert "gtm.crm_upsert" in intent.forbidden_outcomes
    assert "gtm.email_send" in intent.forbidden_outcomes


def test_internal_crm_source_never_becomes_a_write_or_unbound_branch() -> None:
    intent = interpret_instruction(
        "Use Ajenda internal CRM records, qualify the strongest three, and draft introductions. Do not send."
    )
    assert "persist_internal_crm" not in intent.requested_outcomes
    jobs = route_jobs_for_intent(intent)
    assert "research.discover_prospects" not in {job.job_key for job in jobs}
    selections, missing = resolve_jobs(jobs, intent=intent)
    assert missing == []
    steps = compile_planned_steps(selections, intent=intent)
    assert [step.action_name for step in steps] == ["record.search", "sales.qualify", "gtm.email_draft"]
    assert all("ability-record-search" in step.depends_on or step.action_name == "record.search" for step in steps)
    assert any(
        binding["from_step"] == "ability-record-search" and binding["output_path"] == "$.crm_records"
        for step in steps[1:]
        for binding in step.input_bindings
    )


def test_qualification_scores_and_reasons_are_a_supported_deliverable() -> None:
    intent = interpret_instruction(
        "Qualify five software development companies in Austin. Return qualification scores and reasons. "
        "Do not modify records or send messages."
    )
    assert "qualify_prospects" in intent.requested_outcomes
    assert intent.target_entities[0].industry == "software development"
    assert intent.target_entities[0].location == "Austin"
    assert not intent.ambiguity


def test_direct_crm_record_read_does_not_route_web_discovery() -> None:
    intent = interpret_instruction(
        "Read approved CRM records for roofing prospects in Austin, summarize the strongest qualification signals."
    )
    assert "read_crm" in intent.requested_outcomes
    assert "research_prospects" not in intent.requested_outcomes
    assert "hubspot_source" in intent.context_requirements
    assert intent.target_entities[0].name == "roofing prospects in Austin"


def test_crm_record_for_extracts_named_company() -> None:
    intent = interpret_instruction(
        "Read the approved HubSpot CRM record for Acme Roofing and produce a research report."
    )
    assert intent.target_entities[0].name == "Acme Roofing"


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
    graph = compile_task_graph_preview(steps, selections=[selection])
    node = graph["nodes"][0]
    cred = node["input_contract"].get("credential_reference")
    assert cred is not None
    assert "execution_constraints" not in node["input_contract"]
