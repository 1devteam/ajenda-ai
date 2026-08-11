"""Knowledge Qualification Slice 1 declarative ability manifests."""

from backend.services.abilities.manifest import AbilityManifest, AbilityRiskLevel
from backend.services.tools.schemas import SideEffectClass

KNOWLEDGE_ABILITY_MANIFESTS: tuple[AbilityManifest, ...] = (
    AbilityManifest(
        ability_id="analysis-qualify-pattern-knowledge",
        display_name="Analysis Qualify Pattern Knowledge",
        action_name="analysis.qualify_pattern_knowledge",
        provider="ajenda_analysis",
        capability_name="analysis",
        capability_version="1",
        adapter_name="ajenda-analysis",
        adapter_version="1",
        input_schema_ref="backend.services.tools.analysis_actions.QualifyPatternKnowledgeInput",
        output_schema_ref="backend.services.tools.schemas.ActionResult",
        side_effect_class=SideEffectClass.NONE,
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
