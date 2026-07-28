"""Interpreter maps natural contacts language to enrich + CRM outcomes."""

from backend.services.mission_composition.intent_interpreter import interpret_instruction


def test_add_to_contacts_and_collect_info_are_recognized() -> None:
    intent = interpret_instruction(
        "find three roofing companies in the fayetteville Arkansas area "
        "collect contact info for each and add them to contacts"
    )
    assert "research_prospects" in intent.requested_outcomes
    assert "enrich_contacts" in intent.requested_outcomes
    assert "update_crm" in intent.requested_outcomes
    assert intent.requested_quantity == 3
    assert intent.unmatched_material_clauses == []
    assert intent.coverage_score >= 0.99
    assert intent.ambiguity == []
    assert intent.target_entities
    assert intent.target_entities[0].industry == "roofing"


def test_save_to_crm_contacts_phrase() -> None:
    intent = interpret_instruction(
        "Find three roofing companies in Fayetteville Arkansas, "
        "collect contact details for each, and save them to CRM contacts. Do not send emails."
    )
    assert "update_crm" in intent.requested_outcomes
    assert intent.send_policy.mode == "forbid"


def test_do_not_add_to_contacts_suppresses_crm_write() -> None:
    intent = interpret_instruction("Find three roofing companies in Austin, but don't add them to contacts")
    assert "research_prospects" in intent.requested_outcomes
    assert "update_crm" not in intent.requested_outcomes
    assert "gtm.crm_upsert" in intent.forbidden_outcomes


def test_add_to_contacts_depends_on_discovery_and_binds() -> None:
    from backend.services.mission_composition.action_inputs import build_action_input
    from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
    from backend.services.mission_composition.plan_compiler import compile_planned_steps
    from backend.services.operating_charter import default_operating_charter

    intent = interpret_instruction("Find three roofing companies in Austin and add them to contacts")
    jobs = route_jobs_for_intent(intent)
    assert "research.discover_prospects" in {j.job_key for j in jobs}
    assert "crm.pipeline_maintenance" in {j.job_key for j in jobs}
    selections, _ = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    steps = compile_planned_steps(selections, intent=intent)
    crm = [s for s in steps if s.job_key == "crm.pipeline_maintenance"]
    assert crm and crm[0].depends_on
    payload = build_action_input(action_name="gtm.crm_upsert", intent=intent)
    assert payload["data"]["company"] == "pending.binding.company"
    assert payload["context"]["binding_required"] is True
