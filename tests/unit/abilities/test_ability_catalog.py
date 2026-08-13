from __future__ import annotations

from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION, INTERNAL_ABILITY_MANIFESTS
from backend.services.abilities.rollout_validation import validate_manifest_collection
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import SideEffectClass


def test_internal_ability_catalog_has_unique_actions_and_ids() -> None:
    action_names = [manifest.action_name for manifest in INTERNAL_ABILITY_MANIFESTS]
    ability_ids = [manifest.ability_id for manifest in INTERNAL_ABILITY_MANIFESTS]

    assert len(action_names) == len(set(action_names))
    assert len(ability_ids) == len(set(ability_ids))
    assert set(ABILITY_MANIFESTS_BY_ACTION) == set(action_names)


def test_internal_ability_catalog_covers_default_registry() -> None:
    registry = get_default_action_registry(rebuild=True)

    validate_manifest_collection(
        manifests=INTERNAL_ABILITY_MANIFESTS,
        registered_actions=registry.actions,
        require_all_registered=True,
    )


def test_sales_research_manifest_declares_hybrid_external_read_risk() -> None:
    manifest = ABILITY_MANIFESTS_BY_ACTION["sales.research"]

    assert manifest.side_effect_class == SideEffectClass.INTERNAL_READ
    assert manifest.max_side_effect_class == SideEffectClass.EXTERNAL_READ
    assert manifest.resolver_side_effect_classes == (
        SideEffectClass.INTERNAL_READ,
        SideEffectClass.EXTERNAL_READ,
    )


def test_gtm_crm_upsert_manifest_declares_dynamic_external_write_risk() -> None:
    manifest = ABILITY_MANIFESTS_BY_ACTION["gtm.crm_upsert"]

    assert manifest.side_effect_class == SideEffectClass.INTERNAL_WRITE
    assert manifest.max_side_effect_class == SideEffectClass.EXTERNAL_WRITE
    assert manifest.resolver_side_effect_classes == (
        SideEffectClass.INTERNAL_WRITE,
        SideEffectClass.EXTERNAL_WRITE,
    )


def test_http_request_manifest_declares_dynamic_external_write_risk() -> None:
    manifest = ABILITY_MANIFESTS_BY_ACTION["http.request"]

    assert manifest.side_effect_class == SideEffectClass.EXTERNAL_READ
    assert manifest.max_side_effect_class == SideEffectClass.EXTERNAL_WRITE
    assert manifest.resolver_side_effect_classes == (
        SideEffectClass.EXTERNAL_READ,
        SideEffectClass.EXTERNAL_WRITE,
    )
    assert manifest.approval_required is True
    assert manifest.idempotency_required is True
    assert manifest.readback_required is False
    assert manifest.readback_deferred_reason is not None


def test_write_and_send_manifests_require_approval() -> None:
    for manifest in INTERNAL_ABILITY_MANIFESTS:
        effective_side_effect = manifest.max_side_effect_class or manifest.side_effect_class
        if effective_side_effect.has_side_effect:
            assert manifest.approval_required is True


def test_external_write_send_manifests_require_idempotency() -> None:
    for manifest in INTERNAL_ABILITY_MANIFESTS:
        effective_side_effect = manifest.max_side_effect_class or manifest.side_effect_class
        if effective_side_effect in {
            SideEffectClass.EXTERNAL_WRITE,
            SideEffectClass.EXTERNAL_SEND,
            SideEffectClass.EXTERNAL_PUBLISH,
        }:
            assert manifest.idempotency_required is True


def test_decision_materialization_manifest_declares_internal_read() -> None:
    manifest = ABILITY_MANIFESTS_BY_ACTION["analysis.materialize_decision_learning_signal"]
    assert manifest.provider == "ajenda_analysis"
    assert manifest.side_effect_class == SideEffectClass.INTERNAL_READ
    assert manifest.evidence_required is True
    assert manifest.evidence_expectations == ("action_result_evidence",)
    assert "analysis.evaluate_decision_effectiveness" not in ABILITY_MANIFESTS_BY_ACTION
    assert "analysis.extract_decision_learning_signal" not in ABILITY_MANIFESTS_BY_ACTION


def test_attribution_integrity_action_has_non_side_effecting_manifest() -> None:
    manifest = ABILITY_MANIFESTS_BY_ACTION["analysis.assess_attribution_integrity"]

    assert manifest.provider == "ajenda_analysis"
    assert manifest.side_effect_class == SideEffectClass.NONE
    assert manifest.evidence_required is True
    assert manifest.evidence_expectations == ("action_result_evidence",)


def test_experience_intelligence_actions_have_non_side_effecting_manifests() -> None:
    for action in (
        "analysis.compare_experiences",
        "analysis.assess_experience_recurrence",
    ):
        manifest = ABILITY_MANIFESTS_BY_ACTION[action]
        assert manifest.provider == "ajenda_analysis"
        assert manifest.side_effect_class == SideEffectClass.NONE
        assert manifest.evidence_required is True
        assert manifest.evidence_expectations == ("action_result_evidence",)
        assert manifest.enabled_by_default is False


def test_knowledge_qualification_action_has_non_side_effecting_manifest() -> None:
    manifest = ABILITY_MANIFESTS_BY_ACTION["analysis.qualify_pattern_knowledge"]
    assert manifest.ability_id == "analysis-qualify-pattern-knowledge"
    assert manifest.provider == "ajenda_analysis"
    assert manifest.side_effect_class == SideEffectClass.NONE
    assert manifest.evidence_required is True
    assert manifest.evidence_expectations == ("action_result_evidence",)
    assert manifest.enabled_by_default is False


def test_knowledge_persistence_manifest_is_governed_internal_write() -> None:
    manifest = ABILITY_MANIFESTS_BY_ACTION["knowledge.record_qualification"]
    assert manifest.ability_id == "knowledge-record-qualification"
    assert manifest.provider == "ajenda_knowledge"
    assert manifest.side_effect_class == SideEffectClass.INTERNAL_WRITE
    assert manifest.approval_required is True
    assert manifest.idempotency_required is False
    assert manifest.evidence_expectations == ("action_result_evidence",)
    assert manifest.enabled_by_default is False


def test_durable_experience_consolidation_manifest_is_governed_internal_write() -> None:
    manifest = ABILITY_MANIFESTS_BY_ACTION["knowledge.consolidate_learning_history"]
    assert manifest.side_effect_class == SideEffectClass.INTERNAL_WRITE
    assert manifest.approval_required is True
    assert manifest.enabled_by_default is False


def test_knowledge_lifecycle_manifest_is_governed_internal_read() -> None:
    manifest = ABILITY_MANIFESTS_BY_ACTION["knowledge.resolve_current_state"]
    assert manifest.ability_id == "knowledge-resolve-current-state"
    assert manifest.provider == "ajenda_knowledge"
    assert manifest.side_effect_class == SideEffectClass.INTERNAL_READ
    assert manifest.approval_required is False
    assert manifest.evidence_required is True
    assert manifest.enabled_by_default is False


def test_knowledge_retrieval_manifest_is_disabled_internal_read() -> None:
    manifest = ABILITY_MANIFESTS_BY_ACTION["knowledge.retrieve_current"]
    assert manifest.ability_id == "knowledge-retrieve-current"
    assert manifest.provider == "ajenda_knowledge"
    assert manifest.side_effect_class == SideEffectClass.INTERNAL_READ
    assert manifest.approval_required is False
    assert manifest.evidence_required is True
    assert manifest.enabled_by_default is False


def test_knowledge_applicability_manifest_is_disabled_internal_read() -> None:
    manifest = ABILITY_MANIFESTS_BY_ACTION["knowledge.evaluate_applicability"]
    assert manifest.ability_id == "knowledge-evaluate-applicability"
    assert manifest.provider == "ajenda_knowledge"
    assert manifest.side_effect_class == SideEffectClass.INTERNAL_READ
    assert manifest.approval_required is False
    assert manifest.evidence_required is True
    assert manifest.enabled_by_default is False
