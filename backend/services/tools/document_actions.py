from __future__ import annotations

from backend.services.document_artifacts import DOCUMENT_RECORD_TYPE, read_artifact
from backend.services.draft_generation import generate_and_persist_draft
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.record_store import resolve_record_store
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    DocumentGenerateInput,
    DocumentReadInput,
    DocumentSearchInput,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
)


def _write_evidence(
    *,
    context: ActionRuntimeContext,
    action: str,
    summary: str,
    payload: dict[str, object],
) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="document_actions",
        action_name=action,
        tool_provider="ajenda_document",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=payload,
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        provenance={},
    )


def _read_evidence(
    *,
    context: ActionRuntimeContext,
    action: str,
    summary: str,
    payload: dict[str, object],
) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="document_actions",
        action_name=action,
        tool_provider="ajenda_document",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=payload,
        side_effect_class=SideEffectClass.INTERNAL_READ,
        provenance={},
    )


def document_generate_handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = DocumentGenerateInput.model_validate(invocation.input)
    output = generate_and_persist_draft(
        context,
        artifact_type=payload.artifact_type,
        topic=payload.topic,
        tone=payload.tone,
        recipient=payload.recipient,
        recipient_name=payload.recipient_name,
        extra_context=payload.context,
    )
    mode = output.get("generation_mode", "template")
    summary = f"Generated {payload.artifact_type} artifact ({mode})."
    return ActionResult(
        action=invocation.action,
        provider="ajenda_document",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=output,
        evidence=[_write_evidence(context=context, action=invocation.action, summary=summary, payload=output)],
        summary=summary,
        confidence=0.82 if mode == "llm" else 0.7,
    )


def document_search_handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = DocumentSearchInput.model_validate(invocation.input)
    filters: dict[str, object] = {}
    if payload.artifact_type:
        filters["artifact_type"] = payload.artifact_type.strip().lower()
    if payload.review_status:
        filters["review_status"] = payload.review_status.strip().lower()

    matches = resolve_record_store(context).search_records(
        tenant_id=context.tenant_id,
        record_type=DOCUMENT_RECORD_TYPE,
        query=payload.query,
        filters=filters,
        limit=payload.limit,
    )
    items = [{**item, "artifact_id": item.get("id")} for item in matches]
    output = {
        "query": payload.query,
        "filters": filters,
        "count": len(items),
        "artifacts": items,
    }
    summary = f"Found {len(items)} clerical document artifact(s)."
    return ActionResult(
        action=invocation.action,
        provider="ajenda_document",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output=output,
        evidence=[_read_evidence(context=context, action=invocation.action, summary=summary, payload=output)],
        summary=summary,
        confidence=0.9,
    )


def document_read_handler(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = DocumentReadInput.model_validate(invocation.input)
    session_factory = context.session_factory
    artifact: dict[str, object] | None = None
    if session_factory is not None:
        session = session_factory()
        try:
            loaded = read_artifact(session, tenant_id=context.tenant_id, artifact_id=payload.artifact_id)
            if loaded is not None:
                artifact = dict(loaded)
        finally:
            session.close()
    if artifact is None:
        record = resolve_record_store(context).read_record(
            tenant_id=context.tenant_id,
            record_type=DOCUMENT_RECORD_TYPE,
            record_id=payload.artifact_id,
        )
        if record is not None:
            artifact = {**record, "artifact_id": record.get("id", payload.artifact_id)}

    if artifact is None:
        output = {"artifact_id": payload.artifact_id, "found": False}
        summary = f"Document artifact {payload.artifact_id!r} not found."
        return ActionResult(
            action=invocation.action,
            provider="ajenda_document",
            side_effect_class=SideEffectClass.INTERNAL_READ,
            output=output,
            evidence=[_read_evidence(context=context, action=invocation.action, summary=summary, payload=output)],
            summary=summary,
            confidence=0.5,
        )

    output = {"artifact_id": payload.artifact_id, "found": True, "artifact": artifact}
    summary = f"Read document artifact {payload.artifact_id!r}."
    return ActionResult(
        action=invocation.action,
        provider="ajenda_document",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output=output,
        evidence=[_read_evidence(context=context, action=invocation.action, summary=summary, payload=output)],
        summary=summary,
        confidence=0.95,
    )


def register_document_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="document.generate",
            handler=document_generate_handler,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
            provider="ajenda_document",
            input_model=DocumentGenerateInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="document.search",
            handler=document_search_handler,
            side_effect_class=SideEffectClass.INTERNAL_READ,
            provider="ajenda_document",
            input_model=DocumentSearchInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="document.read",
            handler=document_read_handler,
            side_effect_class=SideEffectClass.INTERNAL_READ,
            provider="ajenda_document",
            input_model=DocumentReadInput,
        )
    )
