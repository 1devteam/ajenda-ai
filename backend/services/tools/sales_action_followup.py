"""Sales follow-up drafting and internal activity/task actions."""

from backend.services.tools.sales_action_common import _evidence
from backend.services.tools.sales_action_records import record_write
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    FollowupDraftInput,
    RecordWriteInput,
    SideEffectClass,
    ToolInvocation,
)


def sales_draft_followup(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = FollowupDraftInput.model_validate(invocation.input)
    from backend.services.draft_generation import generate_and_persist_draft

    output = generate_and_persist_draft(
        context,
        artifact_type="follow_up",
        topic=payload.topic,
        tone=payload.tone,
        recipient_name=payload.recipient_name,
        extra_context=payload.context,
    )
    mode = output.get("generation_mode", "template")
    summary = f"Drafted follow-up message ({mode}) without sending it."
    return ActionResult(
        action="sales.draft_followup",
        provider="local_sales",
        side_effect_class=SideEffectClass.NONE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.draft_followup",
                provider="local_sales",
                summary=summary,
                payload=output,
                confidence=0.8 if mode == "llm" else 0.74,
            )
        ],
        summary=summary,
        confidence=0.8 if mode == "llm" else 0.74,
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
