from __future__ import annotations

from typing import Any

from backend.services.plugins.crm_client import default_crm_client, is_live_external_crm_result
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.record_store import RecordStore, record_store_limitations, resolve_record_store
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    FollowupDraftInput,
    RecordReadInput,
    RecordSearchInput,
    RecordWriteInput,
    RuntimeCredentialMaterial,
    SalesLeadInput,
    SideEffectClass,
    ToolInvocation,
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
        side_effect_class=side_effect_class,
    )


def record_search(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RecordSearchInput.model_validate(invocation.input)
    records = _provider(context).search_records(
        tenant_id=context.tenant_id,
        record_type=payload.record_type,
        query=payload.query,
        filters=payload.filters,
        limit=payload.limit,
    )
    inspected = [str(record["id"]) for record in records if "id" in record]
    output = {"record_type": payload.record_type, "records": records, "count": len(records)}
    summary = f"Found {len(records)} {payload.record_type} record(s)."
    return ActionResult(
        action="record.search",
        provider="local_records",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="record.search",
                provider="local_records",
                summary=summary,
                payload=output,
                inspected=inspected,
            )
        ],
        records_inspected=inspected,
        summary=summary,
        confidence=1.0,
    )


def record_read(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RecordReadInput.model_validate(invocation.input)
    record = _provider(context).read_record(
        tenant_id=context.tenant_id,
        record_type=payload.record_type,
        record_id=payload.record_id,
    )
    output = {"record_type": payload.record_type, "record": record, "found": record is not None}
    summary = f"Read {payload.record_type} record {payload.record_id}: {'found' if record else 'not found'}."
    inspected = [payload.record_id] if record else []
    return ActionResult(
        action="record.read",
        provider="local_records",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="record.read",
                provider="local_records",
                summary=summary,
                payload=output,
                inspected=inspected,
            )
        ],
        records_inspected=inspected,
        summary=summary,
        confidence=1.0,
    )


def record_write(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RecordWriteInput.model_validate(invocation.input)
    record = _provider(context).write_record(
        tenant_id=context.tenant_id,
        record_type=payload.record_type,
        record_id=payload.record_id,
        data=payload.data,
    )
    changed = [str(record["id"])]
    output = {"record_type": payload.record_type, "record": record}
    summary = f"Wrote {payload.record_type} record {record['id']} in local proof provider."
    return ActionResult(
        action="record.write",
        provider="local_records",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="record.write",
                provider="local_records",
                summary=summary,
                payload=output,
                changed=changed,
                side_effect_class=SideEffectClass.INTERNAL_WRITE,
            )
        ],
        records_changed=changed,
        summary=summary,
        confidence=1.0,
    )


def sales_research(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = SalesLeadInput.model_validate(invocation.input)
    account_id = payload.account_id or str(payload.lead.get("account_id", ""))
    related = []
    if account_id:
        account = _provider(context).read_record(
            tenant_id=context.tenant_id, record_type="account", record_id=account_id
        )
        if account:
            related.append(account)

    cred: RuntimeCredentialMaterial | dict[str, Any] | None = context.runtime_credentials.get(
        "sales.research"
    ) or context.runtime_credentials.get("crm.research")
    company = str(payload.lead.get("company", ""))
    domain = str(payload.lead.get("domain", "") or "")
    search = default_crm_client().search(
        context=context,
        company=company,
        domain=domain,
        credential=cred,
        invocation=invocation,
        action_name="sales.research",
    )

    use_external = is_live_external_crm_result(
        source=search.source,
        real=search.real,
        error=search.error,
    )
    provider = "ajenda_brain"
    side_effect_class = SideEffectClass.INTERNAL_READ
    research_notes = (
        [f"external CRM plugin search via {search.source} (count={search.count})"]
        if use_external
        else [f"Ajenda central brain search (count={search.count})"]
    )
    if search.error:
        research_notes.append(f"external attempt failed: {search.error}; used internal brain fallback")

    output = {
        "lead": payload.lead,
        "related_records": related,
        "crm_matches": search.results,
        "research_notes": research_notes,
        "real": True,
        "plugin_required": use_external,
        "source": search.source,
    }
    if use_external and cred is not None:
        output["credential_reference"] = {
            "provider": getattr(getattr(cred, "reference", None), "provider", None)
            if not isinstance(cred, dict)
            else cred.get("provider"),
        }
        if search.status_code is not None:
            output["real_response"] = {"status_code": search.status_code}
        if invocation.idempotency_key:
            output["idempotency_key"] = invocation.idempotency_key

    inspected = [str(item["id"]) for item in related if "id" in item]
    inspected.extend(str(item["id"]) for item in search.results if isinstance(item, dict) and item.get("id"))
    summary = f"Researched lead with {len(related)} related record(s) and {search.count} CRM match(es)." + (
        " via external plugin" if use_external else " via Ajenda brain"
    )
    return ActionResult(
        action="sales.research",
        provider=provider,
        side_effect_class=side_effect_class,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.research",
                provider=provider,
                summary=summary,
                payload=output,
                inspected=inspected,
                side_effect_class=side_effect_class,
                confidence=0.9 if use_external else 0.85,
            )
        ],
        records_inspected=inspected,
        summary=summary,
        confidence=0.9 if use_external else 0.85,
    )


def sales_qualify(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = SalesLeadInput.model_validate(invocation.input)
    lead = payload.lead
    fit_points = 0
    reasons: list[str] = []
    if lead.get("company") or payload.account_id:
        fit_points += 35
        reasons.append("company/account context present")
    if lead.get("role") or lead.get("title"):
        fit_points += 25
        reasons.append("buyer role context present")
    if lead.get("intent") or payload.context.get("intent"):
        fit_points += 25
        reasons.append("intent signal present")
    if lead.get("email"):
        fit_points += 15
        reasons.append("contactability present")
    score = min(fit_points, 100)
    qualified = score >= 60
    output = {
        "score": score,
        "qualified": qualified,
        "reasons": reasons or ["insufficient local qualification signals"],
    }
    summary = f"Lead qualification score is {score}; qualified={qualified}."
    return ActionResult(
        action="sales.qualify",
        provider="local_sales",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.qualify",
                provider="local_sales",
                summary=summary,
                payload=output,
                confidence=0.72,
            )
        ],
        summary=summary,
        confidence=0.72,
    )


def sales_score_lead(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    result = sales_qualify(invocation, context)
    output = {
        "lead_score": result.output["score"],
        "score_band": "high" if result.output["score"] >= 75 else "medium" if result.output["score"] >= 50 else "low",
        "reasons": result.output["reasons"],
    }
    summary = f"Lead score is {output['lead_score']} ({output['score_band']})."
    return ActionResult(
        action="sales.score_lead",
        provider="local_sales",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.score_lead",
                provider="local_sales",
                summary=summary,
                payload=output,
                confidence=0.72,
            )
        ],
        summary=summary,
        confidence=0.72,
    )


def sales_recommend_next_action(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = SalesLeadInput.model_validate(invocation.input)
    qualify_result = sales_qualify(invocation, context)
    score = int(qualify_result.output["score"])
    recommendation = "draft_followup" if score >= 60 else "research_more"
    rationale = (
        "Qualification score is high enough for follow-up."
        if score >= 60
        else "More account/contact context is needed."
    )
    output = {"recommendation": recommendation, "rationale": rationale, "lead": payload.lead, "score": score}
    summary = f"Recommended next action: {recommendation}."
    return ActionResult(
        action="sales.recommend_next_action",
        provider="local_sales",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.recommend_next_action",
                provider="local_sales",
                summary=summary,
                payload=output,
                confidence=0.7,
            )
        ],
        summary=summary,
        confidence=0.7,
    )


def sales_draft_followup(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = FollowupDraftInput.model_validate(invocation.input)
    message = f"Hi {payload.recipient_name}, following up on {payload.topic}. Would you be open to discussing practical next steps?"
    output = {"draft": message, "tone": payload.tone}
    summary = "Drafted local follow-up message without sending it."
    return ActionResult(
        action="sales.draft_followup",
        provider="local_sales",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.draft_followup",
                provider="local_sales",
                summary=summary,
                payload=output,
                confidence=0.74,
            )
        ],
        summary=summary,
        confidence=0.74,
    )


def sales_log_activity(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RecordWriteInput.model_validate(invocation.input)
    write_invocation = ToolInvocation(
        action="record.write",
        input={
            "record_type": "activity",
            "record_id": payload.record_id,
            "data": payload.data,
        },
    )
    result = record_write(write_invocation, context)
    return ActionResult(
        action="sales.log_activity",
        provider="local_sales",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=result.output,
        evidence=[
            _evidence(
                context=context,
                action="sales.log_activity",
                provider="local_sales",
                summary="Logged local sales activity.",
                payload=result.output,
                changed=result.records_changed,
                side_effect_class=SideEffectClass.INTERNAL_WRITE,
            )
        ],
        records_changed=result.records_changed,
        summary="Logged local sales activity.",
        confidence=1.0,
    )


def sales_create_followup_task(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = RecordWriteInput.model_validate(invocation.input)
    write_invocation = ToolInvocation(
        action="record.write",
        input={
            "record_type": "task",
            "record_id": payload.record_id,
            "data": payload.data,
        },
    )
    result = record_write(write_invocation, context)
    return ActionResult(
        action="sales.create_followup_task",
        provider="local_sales",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=result.output,
        evidence=[
            _evidence(
                context=context,
                action="sales.create_followup_task",
                provider="local_sales",
                summary="Created local follow-up task.",
                payload=result.output,
                changed=result.records_changed,
                side_effect_class=SideEffectClass.INTERNAL_WRITE,
            )
        ],
        records_changed=result.records_changed,
        summary="Created local follow-up task.",
        confidence=1.0,
    )


def register_sales_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="record.search", handler=record_search, provider="local_records", input_model=RecordSearchInput
        )
    )
    registry.register(
        ActionDefinition(name="record.read", handler=record_read, provider="local_records", input_model=RecordReadInput)
    )
    registry.register(
        ActionDefinition(
            name="record.write",
            handler=record_write,
            provider="local_records",
            input_model=RecordWriteInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.research",
            handler=sales_research,
            provider="ajenda_brain",
            input_model=SalesLeadInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
            aliases=("crm.research", "crm.read"),
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.qualify", handler=sales_qualify, provider="local_sales", input_model=SalesLeadInput
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.score_lead", handler=sales_score_lead, provider="local_sales", input_model=SalesLeadInput
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.recommend_next_action",
            handler=sales_recommend_next_action,
            provider="local_sales",
            input_model=SalesLeadInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.draft_followup",
            handler=sales_draft_followup,
            provider="local_sales",
            input_model=FollowupDraftInput,
            aliases=("gtm.message_draft",),
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.log_activity",
            handler=sales_log_activity,
            provider="local_sales",
            input_model=RecordWriteInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.create_followup_task",
            handler=sales_create_followup_task,
            provider="local_sales",
            input_model=RecordWriteInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
