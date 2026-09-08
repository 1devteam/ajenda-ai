"""Interpreter maps natural contacts language to enrich + CRM outcomes."""

from backend.services.mission_composition.intent_interpreter import interpret_instruction


def test_add_to_contacts_and_collect_info_are_recognized() -> None:
    intent = interpret_instruction(
        "find three roofing companies in the fayetteville Arkansas area "
        "collect contact info for each and add them to contacts"
    )
    assert "research_prospects" in intent.requested_outcomes
    assert "observe_contacts" in intent.requested_outcomes
    assert "enrich_contacts" not in intent.requested_outcomes
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


def test_market_scope_allows_comparison_qualifier_and_deal_records() -> None:
    intent = interpret_instruction(
        "Find five software development companies in Austin, Texas comparable to 1devteam, "
        "qualify them, save each company and contact in Ajenda internal CRM, and create a deal record for each."
    )
    assert "research_prospects" in intent.requested_outcomes
    assert "qualify_prospects" in intent.requested_outcomes
    assert "persist_internal_crm" in intent.requested_outcomes
    assert intent.target_entities
    assert intent.target_entities[0].industry == "software development"
    assert intent.target_entities[0].location == "Austin"
    assert intent.unmatched_material_clauses == []
    assert not any(item.field == "target_scope" for item in intent.ambiguity)


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
    assert "research.observe_sources" in {j.job_key for j in jobs}
    assert "crm.pipeline_maintenance" in {j.job_key for j in jobs}
    selections, _ = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations={"hubspot"},
    )
    steps = compile_planned_steps(selections, intent=intent)
    crm = [s for s in steps if s.job_key == "crm.pipeline_maintenance"]
    assert crm and crm[0].depends_on
    payload = build_action_input(action_name="gtm.crm_upsert", intent=intent)
    assert payload["data"]["company"] == "pending.binding.company"
    assert payload["context"]["binding_required"] is True


def test_ajenda_internal_crm_uses_distinct_job_and_record_write_graph() -> None:
    from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
    from backend.services.mission_composition.plan_compiler import compile_planned_steps
    from backend.services.operating_charter import default_operating_charter

    intent = interpret_instruction(
        "Research three roofing companies in Austin, observe public contact evidence, "
        "persist the prospects to Ajenda internal CRM, then read back every saved record."
    )
    assert "persist_internal_crm" in intent.requested_outcomes
    assert "update_crm" not in intent.requested_outcomes
    assert "read_crm" not in intent.requested_outcomes

    jobs = route_jobs_for_intent(intent)
    selections, missing = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    internal = next(item for item in selections if item.job_key == "crm.internal_persistence")
    assert internal.action_name == "record.write"
    assert internal.readiness == "ready"
    assert not any(item["provider"] == "hubspot" for item in missing)

    steps = compile_planned_steps(selections, intent=intent)
    persist = next(item for item in steps if item.job_key == "crm.internal_persistence")
    assert set(persist.depends_on) == {
        "ability-web-research",
        "ability-research-observe_contacts",
        "ability-sales-qualify",
    }
    assert {binding["input_path"] for binding in persist.input_bindings} == {
        "$.input.context.qualified_prospects",
        "$.input.context.observed_contacts",
    }


def test_explicit_hubspot_crm_write_still_selects_hubspot_upsert() -> None:
    from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent

    intent = interpret_instruction("Research three roofing companies and save them to HubSpot CRM.")
    selections, _ = resolve_jobs(route_jobs_for_intent(intent), intent=intent, connected_integrations={"hubspot"})
    external = next(item for item in selections if item.job_key == "crm.pipeline_maintenance")
    assert external.action_name == "gtm.crm_upsert"
    assert external.connection_provider == "hubspot"
