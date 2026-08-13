"""Declarative rollout contract for durable knowledge persistence."""

from backend.services.abilities.manifest import AbilityManifest, AbilityRiskLevel
from backend.services.tools.schemas import SideEffectClass

KNOWLEDGE_PERSISTENCE_ABILITY_MANIFESTS: tuple[AbilityManifest, ...] = (
    AbilityManifest(
        ability_id="knowledge-consolidate-learning-history",
        display_name="Consolidate Durable Learning History",
        action_name="knowledge.consolidate_learning_history",
        provider="ajenda_knowledge",
        capability_name="knowledge",
        capability_version="1",
        adapter_name="ajenda-knowledge",
        adapter_version="1",
        input_schema_ref="backend.services.tools.knowledge_actions.ConsolidateLearningHistoryInput",
        output_schema_ref="backend.services.tools.schemas.ActionResult",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        risk_level=AbilityRiskLevel.LOW,
        approval_required=True,
        idempotency_required=False,
        evidence_required=True,
        evidence_expectations=("action_result_evidence",),
        readback_required=False,
        readback_deferred_reason="Deterministic Qualification and Ledger identities confirm replay inline.",
        enabled_by_default=False,
    ),
    AbilityManifest(
        ability_id="knowledge-record-qualification",
        display_name="Knowledge Record Qualification",
        action_name="knowledge.record_qualification",
        provider="ajenda_knowledge",
        capability_name="knowledge",
        capability_version="1",
        adapter_name="ajenda-knowledge",
        adapter_version="1",
        input_schema_ref="backend.services.tools.knowledge_actions.RecordKnowledgeQualificationInput",
        output_schema_ref="backend.services.tools.schemas.ActionResult",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        risk_level=AbilityRiskLevel.LOW,
        approval_required=True,
        idempotency_required=False,
        evidence_required=True,
        evidence_expectations=("action_result_evidence",),
        readback_required=False,
        readback_deferred_reason="The immutable semantic identity replay confirms the durable write inline.",
        enabled_by_default=False,
    ),
)
