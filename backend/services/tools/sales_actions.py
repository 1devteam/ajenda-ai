from __future__ import annotations

from typing import Any

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.local_records import LocalRecordProvider, default_local_record_provider
from backend.services.tools.schemas import (
    ActionExecutionContext,
    ActionResult,
    EvidenceItem,
    FollowupTaskInput,
    RecordReadInput,
    RecordSearchInput,
    RecordWriteInput,
    SalesActivityInput,
    SalesDraftInput,
    SalesRecordInput,
)


def _provider(context: ActionExecutionContext) -> LocalRecordProvider:
    candidate = context.extras.get("record_provider")
    if isinstance(candidate, LocalRecordProvider):
        return candidate
    return default_local_record_provider()


def _evidence(*, source: str, summary: str, payload: dict[str, Any], confidence: float = 1.0) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="action_result",
        evidence_source=source,
        summary=summary,
        structured_payload=payload,
        confidence=confidence,
        provenance_metadata={"runtime": "tool.invoke"},
        trust_signal={"provider": "local"},
    )


def _record_to_dict(record: Any) -> dict[str, Any]:
    if hasattr(record, "model_dump"):
        return record.model_dump(mode="json")
    return dict(record)


def record_search(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    parsed = RecordSearchInput.model_validate(payload)
    if parsed.simulate_provider_failure:
        raise ValueError("simulated local record provider failure")
    records = _provider(context).search_records(
        tenant_id=context.tenant_id,
        record_type=parsed.record_type,
        query=parsed.query,
        filters=parsed.filters,
        limit=parsed.limit,
    )
    output = {
        "record_type": parsed.record_type,
        "query": parsed.query,
        "count": len(records),
        "records": [_record_to_dict(record) for record in records],
    }
    return ActionResult(
        action="record.search",
        output=output,
        evidence=[
            _evidence(source="tool.invoke.record.search", summary=f"Found {len(records)} records.", payload=output)
        ],
    )


def record_read(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    parsed = RecordReadInput.model_validate(payload)
    if parsed.simulate_provider_failure:
        raise ValueError("simulated local record provider failure")
    record = _provider(context).read_record(
        tenant_id=context.tenant_id,
        record_type=parsed.record_type,
        record_id=parsed.record_id,
    )
    output = {"record": _record_to_dict(record)}
    return ActionResult(
        action="record.read",
        output=output,
        evidence=[
            _evidence(source="tool.invoke.record.read", summary=f"Read {parsed.record_type} record.", payload=output)
        ],
    )


def record_write(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    parsed = RecordWriteInput.model_validate(payload)
    if parsed.simulate_provider_failure:
        raise ValueError("simulated local record provider failure")
    record = _provider(context).write_record(
        tenant_id=context.tenant_id,
        record_type=parsed.record_type,
        record_id=parsed.record_id,
        name=parsed.name,
        fields=parsed.fields,
    )
    output = {"record": _record_to_dict(record)}
    return ActionResult(
        action="record.write",
        side_effect_class="internal_write",
        output=output,
        evidence=[
            _evidence(source="tool.invoke.record.write", summary=f"Wrote {parsed.record_type} record.", payload=output)
        ],
    )


def _read_sales_record(payload: dict[str, Any], context: ActionExecutionContext) -> dict[str, Any]:
    parsed = SalesRecordInput.model_validate(payload)
    record = _provider(context).read_record(
        tenant_id=context.tenant_id,
        record_type=parsed.record_type,
        record_id=parsed.record_id,
    )
    return _record_to_dict(record)


def _score_record(record: dict[str, Any]) -> tuple[int, list[str]]:
    fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
    score = 40
    reasons: list[str] = []
    employee_count = fields.get("employee_count")
    if isinstance(employee_count, int) and employee_count >= 50:
        score += 20
        reasons.append("company_size_fit")
    budget = fields.get("budget")
    if isinstance(budget, (int, float)) and budget >= 10000:
        score += 20
        reasons.append("budget_fit")
    urgency = str(fields.get("urgency", "")).lower()
    if urgency in {"high", "urgent"}:
        score += 15
        reasons.append("urgent_need")
    if fields.get("decision_maker") is True:
        score += 5
        reasons.append("decision_maker_identified")
    return min(score, 100), reasons or ["baseline_fit"]


def sales_research(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    record = _read_sales_record(payload, context)
    fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
    output = {
        "record": record,
        "research_summary": f"{record['name']} profile reviewed for sales readiness.",
        "signals": sorted(str(key) for key in fields.keys()),
    }
    return ActionResult(
        action="sales.research",
        output=output,
        evidence=[
            _evidence(source="tool.invoke.sales.research", summary="Completed local sales research.", payload=output)
        ],
    )


def sales_score_lead(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    record = _read_sales_record(payload, context)
    score, reasons = _score_record(record)
    output = {"record_id": record["record_id"], "score": score, "reasons": reasons}
    return ActionResult(
        action="sales.score_lead",
        output=output,
        evidence=[_evidence(source="tool.invoke.sales.score_lead", summary=f"Lead scored {score}.", payload=output)],
    )


def sales_qualify(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    score_result = sales_score_lead(payload, context)
    score = int(score_result.output["score"])
    output = {
        **score_result.output,
        "qualified": score >= 70,
        "qualification_status": "qualified" if score >= 70 else "needs_nurture",
    }
    return ActionResult(
        action="sales.qualify",
        output=output,
        evidence=[
            _evidence(source="tool.invoke.sales.qualify", summary="Completed lead qualification.", payload=output)
        ],
    )


def sales_recommend_next_action(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    qualify_result = sales_qualify(payload, context)
    qualified = bool(qualify_result.output["qualified"])
    output = {
        **qualify_result.output,
        "recommended_action": "schedule_discovery_call" if qualified else "send_nurture_followup",
        "rationale": "High-fit lead is ready for a sales conversation." if qualified else "Lead needs more nurturing.",
    }
    return ActionResult(
        action="sales.recommend_next_action",
        output=output,
        evidence=[
            _evidence(
                source="tool.invoke.sales.recommend_next_action",
                summary="Recommended next sales action.",
                payload=output,
            )
        ],
    )


def sales_draft_followup(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    parsed = SalesDraftInput.model_validate(payload)
    draft = (
        f"Hi {parsed.recipient_name},\n\n"
        f"I wanted to follow up on {parsed.topic} for {parsed.company_name}. "
        "Would it be useful to compare notes this week?\n\nBest,\nAJENDA-AI"
    )
    output = {
        "recipient_name": parsed.recipient_name,
        "company_name": parsed.company_name,
        "topic": parsed.topic,
        "tone": parsed.tone,
        "draft": draft,
        "external_send_authorized": False,
    }
    return ActionResult(
        action="sales.draft_followup",
        output=output,
        evidence=[
            _evidence(source="tool.invoke.sales.draft_followup", summary="Drafted follow-up message.", payload=output)
        ],
    )


def sales_log_activity(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    parsed = SalesActivityInput.model_validate(payload)
    record = _provider(context).write_record(
        tenant_id=context.tenant_id,
        record_type="activity",
        name=parsed.summary,
        fields={"record_id": parsed.record_id, "activity_type": parsed.activity_type, **parsed.metadata},
    )
    output = {"activity": _record_to_dict(record)}
    return ActionResult(
        action="sales.log_activity",
        side_effect_class="internal_write",
        output=output,
        evidence=[_evidence(source="tool.invoke.sales.log_activity", summary="Logged sales activity.", payload=output)],
    )


def sales_create_followup_task(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    parsed = FollowupTaskInput.model_validate(payload)
    record = _provider(context).write_record(
        tenant_id=context.tenant_id,
        record_type="followup_task",
        name=parsed.title,
        fields={"record_id": parsed.record_id, "due_at": parsed.due_at, **parsed.metadata},
    )
    output = {"followup_task": _record_to_dict(record)}
    return ActionResult(
        action="sales.create_followup_task",
        side_effect_class="internal_write",
        output=output,
        evidence=[
            _evidence(
                source="tool.invoke.sales.create_followup_task", summary="Created follow-up task.", payload=output
            )
        ],
    )


def register_sales_actions(registry: ActionRegistry) -> None:
    registry.register(ActionDefinition(name="record.search", handler=record_search))
    registry.register(ActionDefinition(name="record.read", handler=record_read))
    registry.register(ActionDefinition(name="record.write", handler=record_write, side_effect_class="internal_write"))
    registry.register(ActionDefinition(name="sales.research", handler=sales_research, aliases=("crm.research",)))
    registry.register(ActionDefinition(name="sales.qualify", handler=sales_qualify))
    registry.register(ActionDefinition(name="sales.score_lead", handler=sales_score_lead))
    registry.register(ActionDefinition(name="sales.recommend_next_action", handler=sales_recommend_next_action))
    registry.register(
        ActionDefinition(name="sales.draft_followup", handler=sales_draft_followup, aliases=("gtm.message_draft",))
    )
    registry.register(
        ActionDefinition(name="sales.log_activity", handler=sales_log_activity, side_effect_class="internal_write")
    )
    registry.register(
        ActionDefinition(
            name="sales.create_followup_task",
            handler=sales_create_followup_task,
            side_effect_class="internal_write",
        )
    )
