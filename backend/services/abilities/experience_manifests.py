"""Experience Intelligence Slice 1 ability manifests."""

from __future__ import annotations

from backend.services.abilities.manifest import AbilityManifest, AbilityRiskLevel
from backend.services.tools.schemas import SideEffectClass

ACTION_RESULT_SCHEMA_REF = "backend.services.tools.schemas.ActionResult"

EXPERIENCE_ABILITY_MANIFESTS: tuple[AbilityManifest, ...] = (
    AbilityManifest(
        ability_id="analysis-compare-experiences",
        display_name="Analysis Compare Experiences (semantic partitions)",
        action_name="analysis.compare_experiences",
        provider="ajenda_analysis",
        capability_name="analysis",
        capability_version="1",
        adapter_name="ajenda-analysis",
        adapter_version="1",
        input_schema_ref="backend.services.tools.analysis_actions.CompareExperiencesInput",
        output_schema_ref=ACTION_RESULT_SCHEMA_REF,
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
    AbilityManifest(
        ability_id="analysis-assess-experience-recurrence",
        display_name="Analysis Assess Experience Recurrence (candidate only)",
        action_name="analysis.assess_experience_recurrence",
        provider="ajenda_analysis",
        capability_name="analysis",
        capability_version="1",
        adapter_name="ajenda-analysis",
        adapter_version="1",
        input_schema_ref="backend.services.tools.analysis_actions.AssessExperienceRecurrenceInput",
        output_schema_ref=ACTION_RESULT_SCHEMA_REF,
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
