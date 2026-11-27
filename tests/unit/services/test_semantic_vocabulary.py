from __future__ import annotations

import pytest

from backend.services.mission_composition import intent_interpreter as interpreter_module
from backend.services.mission_composition.intent_interpreter import (
    _interpret_instruction_pass,
    interpret_instruction,
)
from backend.services.mission_composition.semantic_lattice.resolver import (
    build_semantic_selection as build_modular_semantic_selection,
)
from backend.services.mission_composition.semantic_vocabulary import (
    ALL_SEMANTIC_CONCEPTS,
    SHARED_BUSINESS_CONCEPTS,
    TenantSemanticOverride,
    build_semantic_selection,
    resolve_shared_concept,
)
from backend.services.mission_composition.service import MissionCompositionService


def test_shared_vocabulary_resolves_canonical_ids_and_aliases() -> None:
    assert resolve_shared_concept("prospect").concept_id == "prospect"
    assert resolve_shared_concept("  target account ").concept_id == "prospect"
    assert resolve_shared_concept("prospects").concept_id == "prospect"
    assert resolve_shared_concept("target accounts").concept_id == "prospect"
    assert resolve_shared_concept("follow-up").concept_id == "outreach"


def test_shared_vocabulary_keeps_unknown_terms_unresolved() -> None:
    assert resolve_shared_concept("unmapped business signal") is None


def test_domain_and_industry_overlays_resolve_without_runtime_authority() -> None:
    assert resolve_shared_concept("heat pump").concept_id == "heat_pump"
    assert resolve_shared_concept("storm damage").concept_id == "storm_damage"
    assert resolve_shared_concept("job candidate").concept_id == "candidate"
    assert resolve_shared_concept("SKU").concept_id == "sku"


def test_shared_vocabulary_is_versioned_and_non_authoritative() -> None:
    assert len(SHARED_BUSINESS_CONCEPTS) >= 7
    assert all(concept.version == "1.0.0" for concept in SHARED_BUSINESS_CONCEPTS)
    assert all(concept.grants_execution_authority is False for concept in SHARED_BUSINESS_CONCEPTS)
    assert all(concept.version == "1.0.0" for concept in ALL_SEMANTIC_CONCEPTS)
    assert all(concept.grants_execution_authority is False for concept in ALL_SEMANTIC_CONCEPTS)


def test_semantic_selection_records_outcome_to_job_provenance() -> None:
    selection = build_semantic_selection(
        instruction="Research prospects, qualify them, and prepare outreach drafts.",
        requested_outcomes=("research_prospects", "qualify_prospects", "prepare_outreach"),
        selected_job_keys=(
            "research.discover_prospects",
            "sales.qualify_prospects",
            "email.prepare_outreach",
        ),
    )

    assert selection.concepts == ("prospect", "qualification", "outreach")
    assert {binding.status for binding in selection.bindings} == {"satisfied"}
    assert selection.conflicts == ()
    guidance = {item.component_id: item for item in selection.component_job_guidance}
    assert guidance["gtm.core"].status == "satisfied"
    assert "sales.qualify_prospects" in guidance["gtm.core"].candidate_job_keys
    assert {item.component_id for item in selection.active_component_provenance} >= {"shared_business", "gtm.core"}
    assert all(item.version == "1.0.0" and item.source_reference for item in selection.active_component_provenance)
    assert {item.concept_id for item in selection.concept_provenance} == {
        "prospect",
        "qualification",
        "outreach",
    }
    assert selection.grants_execution_authority is False


def test_modular_resolver_preserves_existing_selection_contract() -> None:
    kwargs = {
        "instruction": "Research HVAC companies offering heat pump maintenance plans in Dallas.",
        "requested_outcomes": ("research_prospects",),
        "selected_job_keys": ("research.discover_prospects",),
    }
    legacy = build_semantic_selection(**kwargs)
    modular = build_modular_semantic_selection(**kwargs)
    assert modular == legacy
    assert modular.grants_execution_authority is False


def test_semantic_selection_exposes_industry_overlay_terms() -> None:
    selection = build_semantic_selection(
        instruction="Research HVAC companies offering heat pump maintenance plans in Dallas.",
        requested_outcomes=("research_prospects",),
        selected_job_keys=("research.discover_prospects",),
    )

    assert {"prospect", "heat_pump", "maintenance_plan"}.issubset(selection.concepts)
    assert {"heat pump", "maintenance plans"}.issubset(selection.matched_terms)
    assert selection.lattice_version == "1.0.0"
    assert selection.active_components == (
        "shared_business",
        "gtm.core",
        "local_service_business",
        "field_service",
        "recurring_service_business",
        "hvac",
    )
    assert selection.conflicts == ()
    assert selection.grants_execution_authority is False


def test_advertising_overlay_is_declarative_and_catalog_only() -> None:
    selection = build_semantic_selection(
        instruction="Analyze paid media campaigns, target audience, ad creative, ad spend, impressions, clicks, and conversions.",
        requested_outcomes=(),
        selected_job_keys=(),
    )

    assert {"campaign", "audience", "creative", "ad_budget", "impression", "click", "ad_conversion"}.issubset(
        selection.concepts
    )
    assert "advertising" in selection.active_components
    assert selection.active_components[:3] == ("shared_business", "gtm.core", "advertising")
    advertising_guidance = next(item for item in selection.component_job_guidance if item.component_id == "advertising")
    assert advertising_guidance.status == "informational"
    assert advertising_guidance.grants_execution_authority is False
    assert selection.grants_execution_authority is False


def test_multi_parent_overlay_inherits_all_required_domains() -> None:
    dental = build_semantic_selection(
        instruction="Research dental patients and appointments in Austin.",
        requested_outcomes=("research_prospects",),
        selected_job_keys=("research.discover_prospects",),
    )
    recruiting = build_semantic_selection(
        instruction="Research recruiting candidates for a software employer.",
        requested_outcomes=("research_prospects",),
        selected_job_keys=("research.discover_prospects",),
    )

    assert {"shared_business", "gtm.core", "healthcare_business", "local_service_business", "dental"}.issubset(
        dental.active_components
    )
    assert {"shared_business", "gtm.core", "professional_services", "b2b_sales", "recruiting"}.issubset(
        recruiting.active_components
    )
    assert dental.component_conflicts == ()
    assert recruiting.component_conflicts == ()


def test_semantic_selection_fails_closed_when_a_required_job_is_missing() -> None:
    selection = build_semantic_selection(
        instruction="Qualify the prospects.",
        requested_outcomes=("qualify_prospects",),
        selected_job_keys=(),
    )

    assert selection.conflicts
    assert selection.bindings[0].status == "conflict"


def test_pre_intent_lattice_resolves_concepts_without_job_binding_conflicts() -> None:
    selection = build_modular_semantic_selection(
        instruction="Research HVAC prospects offering heat pump maintenance in Austin.",
        requested_outcomes=(),
        selected_job_keys=(),
    )
    assert {"prospect", "heat_pump"}.issubset(selection.concepts)
    assert "hvac" in selection.active_components
    assert selection.bindings == ()
    assert selection.conflicts == ()


def test_interpreter_consumes_lattice_concept_evidence_without_changing_meaning() -> None:
    instruction = "Research three HVAC prospects offering heat pump maintenance in Austin."
    selection = build_modular_semantic_selection(
        instruction=instruction,
        requested_outcomes=(),
        selected_job_keys=(),
    )
    intent = interpret_instruction(instruction, semantic_selection=selection)
    direct = interpret_instruction(instruction)
    assert intent.requested_outcomes == direct.requested_outcomes
    assert intent.target_entities == direct.target_entities
    assert intent.requested_quantity == direct.requested_quantity
    assert intent.interpretation_ready == direct.interpretation_ready
    assert any(
        item.field_path == "semantic_concepts.heat_pump"
        and item.source_text == "heat pump"
        and item.rule_id == "semantic_lattice.concept_match"
        for item in intent.interpretation_evidence
    )
    assert "semantic_lattice" in intent.components_executed


def test_existing_post_job_lattice_still_reports_missing_required_job() -> None:
    selection = build_modular_semantic_selection(
        instruction="Qualify the prospects.",
        requested_outcomes=("qualify_prospects",),
        selected_job_keys=(),
    )
    assert any(item.status == "conflict" for item in selection.bindings)


def test_composition_feeds_lattice_concepts_to_interpretation() -> None:
    instruction = "Research three HVAC prospects offering heat pump maintenance in Austin."
    record = MissionCompositionService(db=None).compose(tenant_id="tenant", instruction=instruction)
    matches = {
        item.normalized_value
        for item in record.intent.interpretation_evidence
        if item.rule_id == "semantic_lattice.concept_match"
    }
    assert {"prospect", "heat_pump"}.issubset(matches)
    assert record.composition_provenance.semantic_selection is not None
    assert "hvac" in record.composition_provenance.semantic_selection.active_components
    assert record.intent.requested_quantity == 3


def test_semantic_feedback_revisits_interpretation_and_adds_explicit_qualification() -> None:
    instruction = "Assess lead quality for roofing companies in Austin."
    initial = _interpret_instruction_pass(instruction)
    final = interpret_instruction(instruction)
    assert "qualify_prospects" not in initial.requested_outcomes
    assert "qualify_prospects" in final.requested_outcomes
    assert set(initial.requested_outcomes).issubset(final.requested_outcomes)
    assert final.target_entities == initial.target_entities
    assert final.send_policy == initial.send_policy
    assert final.forbidden_actions == initial.forbidden_actions
    assert any(
        item.rule_id == "semantic_lattice.qualification_feedback" and item.normalized_value == "qualify_prospects"
        for item in final.interpretation_evidence
    )
    assert final.coverage_score >= initial.coverage_score
    assert any(
        step.decision == "accepted" and "qualify_prospects" in step.feedback_hints
        for step in final.interpretation_passes
    )


def test_semantic_feedback_does_not_turn_a_noun_into_requested_work() -> None:
    instruction = "Review the lead quality glossary in the approved business profile."
    first = _interpret_instruction_pass(instruction)
    result = interpret_instruction(instruction)
    assert result.requested_outcomes == first.requested_outcomes
    assert "qualify_prospects" not in result.requested_outcomes


def test_semantic_feedback_respects_explicit_negation() -> None:
    instruction = "Do not assess lead quality. Research roofing companies in Austin."
    first = _interpret_instruction_pass(instruction)
    result = interpret_instruction(instruction)
    assert result.requested_outcomes == first.requested_outcomes
    assert "qualify_prospects" not in result.requested_outcomes


def test_semantic_feedback_terminates_after_no_new_grounded_meaning() -> None:
    instruction = "Assess lead quality for roofing companies in Austin."
    once = interpret_instruction(instruction)
    twice = interpret_instruction(instruction)
    assert once == twice
    assert once.requested_outcomes.count("qualify_prospects") == 1


def test_concept_only_lattice_re_evaluates_outcome_without_missing_job_conflicts() -> None:
    selection = build_modular_semantic_selection(
        instruction="Find three roofing companies in Austin.",
        requested_outcomes=("research_prospects",),
        selected_job_keys=(),
        validate_job_bindings=False,
    )
    assert "prospect" in selection.concepts
    assert selection.bindings[0].status == "informational"
    assert selection.conflicts == ()


def test_interpreter_re_enters_after_lattice_receives_candidate_meaning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = interpreter_module._interpret_instruction_pass
    observed: list[tuple[str, ...]] = []

    def tracked_pass(*args: object, **kwargs: object):
        semantic_selection = kwargs["semantic_selection"]
        observed.append(tuple(semantic_selection.concepts))
        return original(*args, **kwargs)

    monkeypatch.setattr(interpreter_module, "_interpret_instruction_pass", tracked_pass)
    intent = interpret_instruction("Find three roofing companies in Austin.")
    assert "research_prospects" in intent.requested_outcomes
    assert len(observed) == 2
    assert "prospect" not in observed[0]
    assert "prospect" in observed[1]
    assert len(intent.interpretation_passes) == 2
    assert intent.interpretation_passes[0].decision == "initial"
    assert intent.interpretation_passes[1].decision == "accepted"
    assert intent.interpretation_stop_reason == "converged"


def test_tenant_semantic_alias_provenance_survives_interpretation_loop() -> None:
    instruction = "Research priority accounts in Austin."
    override = TenantSemanticOverride(
        concept_id="prospect",
        aliases=("priority accounts",),
        source_reference="test-tenant-profile",
        version="1.0.0",
    )
    selection = build_modular_semantic_selection(
        instruction=instruction,
        requested_outcomes=(),
        selected_job_keys=(),
        tenant_overrides=(override,),
        validate_job_bindings=False,
    )
    intent = interpret_instruction(instruction, semantic_selection=selection)
    assert any(
        entry.rule_id == "semantic_lattice.concept_match"
        and entry.field_path == "semantic_concepts.prospect"
        and entry.source_text == "priority accounts"
        for entry in intent.interpretation_evidence
    )
    assert selection.conflicts == ()


def test_interpretation_pass_history_round_trips_and_accepts_legacy_records() -> None:
    result = interpret_instruction("Find three roofing companies in Austin.")
    payload = result.model_dump(mode="json")
    restored = type(result).model_validate(payload)
    assert restored.interpretation_passes == result.interpretation_passes
    assert restored.interpretation_stop_reason == result.interpretation_stop_reason
    payload.pop("interpretation_passes")
    payload.pop("interpretation_stop_reason")
    payload.pop("semantic_evidence_omitted_count")
    legacy = type(result).model_validate(payload)
    assert legacy.interpretation_passes == []
    assert legacy.interpretation_stop_reason is None
    assert legacy.semantic_evidence_omitted_count == 0
