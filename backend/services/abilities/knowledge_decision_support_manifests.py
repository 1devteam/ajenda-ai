"""Knowledge-Informed Decision Support declarative ability manifest."""

from backend.services.abilities.manifest import AbilityManifest, AbilityRiskLevel
from backend.services.tools.schemas import SideEffectClass

KNOWLEDGE_DECISION_SUPPORT_ABILITY_MANIFESTS: tuple[AbilityManifest, ...] = (
    AbilityManifest(
        ability_id="knowledge-inform-decision",
        display_name="Knowledge-Informed Decision Support",
        action_name="knowledge.inform_decision",
        provider="ajenda_knowledge",
        capability_name="knowledge",
        capability_version="1",
        adapter_name="ajenda-knowledge",
        adapter_version="1",
        input_schema_ref=("backend.services.tools.knowledge_actions.KnowledgeInformedDecisionSupportInput"),
        output_schema_ref="backend.services.tools.schemas.ActionResult",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        risk_level=AbilityRiskLevel.LOW,
        required_permissions=[],
        required_tools=[],
        approval_required=False,
        idempotency_required=False,
        evidence_required=True,
        evidence_expectations=("action_result_evidence",),
        readback_required=False,
        enabled_by_default=False,
    ),
)
