"""Shared sales action provider and evidence helpers."""

from __future__ import annotations

from typing import Any

from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
    EvidenceSourceIdentity,
)

from backend.services.tools.action_registry import ActionRegistry

from backend.services.tools.record_store import (
    RecordStore,
    record_store_limitations,
    resolve_record_store,
)

from backend.services.tools.schemas import (
    ActionRuntimeContext,
    EvidenceItem,
    SideEffectClass,
)

def _provider(context: ActionRuntimeContext) -> RecordStore:
    return resolve_record_store(context)

def _evidence(
    *,
    context: ActionRuntimeContext,
    action: str,
    provider: str,
    summary: str,
    payload: dict[str, Any],
    inspected: list[str] | None = None,
    changed: list[str] | None = None,
    side_effect_class: SideEffectClass = SideEffectClass.NONE,
    confidence: float | None = 1.0,
    source_observation: bool = False,
    source_identity: EvidenceSourceIdentity | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="action_result",
        evidence_source=f"tool.invoke.{action}",
        action_name=action,
        tool_provider=provider,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id is not None else None,
        summary=summary,
        structured_payload=payload,
        records_inspected=inspected or [],
        records_changed=changed or [],
        confidence=confidence,
        limitations=record_store_limitations(context),
        provenance={"runtime_path": "TaskDispatcher -> tool.invoke -> ActionRegistry"},
        lineage=(
            EvidenceLineage(
                artifact_evidence_id=f"action-result:{context.task_id}",
                origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
                source_identity=source_identity,
                resolution=(
                    EvidenceLineageResolution.KNOWN
                    if source_identity is not None
                    else EvidenceLineageResolution.UNKNOWN
                ),
            )
            if source_observation
            else None
        ),
        side_effect_class=side_effect_class,
    )
