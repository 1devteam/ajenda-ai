"""Sales follow-up drafting and internal activity/task actions."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.db.tenant_session import activate_tenant_session
from backend.services.light_crm.records import LightCrmRecordService
from backend.services.light_crm.workflow import complete_internal_crm_upsert
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
    if payload.tenant_id is not None and payload.tenant_id != context.tenant_id:
        raise ValueError("sales.create_followup_task tenant_id must match the runtime tenant")
    if payload.context.get("source") == "mission_composition":
        return _create_composed_followup_tasks(payload=payload, context=context)

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


def _create_composed_followup_tasks(*, payload: RecordWriteInput, context: ActionRuntimeContext) -> ActionResult:
    """Persist follow-up tasks only for tenant-owned contacts bound by the graph."""

    raw_records = payload.context.get("crm_records")
    if not isinstance(raw_records, list) or not raw_records:
        raise ValueError("sales.create_followup_task requires bound CRM contact records")
    if context.session_factory is None or not callable(context.session_factory):
        raise ValueError("sales.create_followup_task requires a durable tenant CRM session")

    requested_quantity = payload.context.get("requested_quantity", 1)
    if (
        not isinstance(requested_quantity, int)
        or isinstance(requested_quantity, bool)
        or not 1 <= requested_quantity <= 50
    ):
        raise ValueError("sales.create_followup_task requested_quantity must be between 1 and 50")
    if payload.context.get("due_policy") != "three_days_after_execution":
        raise ValueError("sales.create_followup_task requires the approved due policy")
    candidates = [dict(item) for item in raw_records if isinstance(item, dict)][:requested_quantity]
    if not candidates:
        raise ValueError("sales.create_followup_task requires CRM records with stable identities")

    session = context.session_factory()
    try:
        activate_tenant_session(session, context.tenant_id)
        crm = LightCrmRecordService(session=session)
        tasks: list[dict[str, Any]] = []
        readback: list[dict[str, Any]] = []
        relationship_ids: list[str] = []
        seen_contact_ids: set[str] = set()
        mission_identity = str(context.mission_id) if context.mission_id is not None else "missionless"
        execution_time = datetime.now(UTC)
        for candidate in candidates:
            contact_id = str(candidate.get("id") or candidate.get("prospect_id") or "").strip()
            if not contact_id:
                raise ValueError("sales.create_followup_task CRM record requires an id")
            if contact_id in seen_contact_ids:
                raise ValueError("sales.create_followup_task CRM contact bindings must be unique")
            seen_contact_ids.add(contact_id)
            contact = crm.read_record(tenant_id=context.tenant_id, record_type="contact", record_id=contact_id)
            if contact is None:
                raise ValueError("sales.create_followup_task bound CRM contact is not visible for tenant")

            task_id = (
                "task-ajenda-"
                + hashlib.sha256(f"{mission_identity}:{context.task_id}:{contact_id}".encode()).hexdigest()[:20]
            )
            existing = crm.read_record(tenant_id=context.tenant_id, record_type="task", record_id=task_id)
            due_at = str(existing.get("due_at") or "").strip() if existing else ""
            if not due_at:
                due_at = (execution_time + timedelta(days=3)).isoformat()
            task_data = {
                "id": task_id,
                "title": str(payload.data.get("title") or "Follow up with existing prospect"),
                "priority": str(payload.data.get("priority") or "normal"),
                "status": str(payload.data.get("status") or "open"),
                "due_at": due_at,
                "related_type": "contact",
                "related_id": contact_id,
                "prospect_id": contact_id,
                "source": "mission_composition:followup",
            }
            written = complete_internal_crm_upsert(
                session=session,
                tenant_id=context.tenant_id,
                record_type="task",
                data=task_data,
                mission_id=str(context.mission_id) if context.mission_id else None,
                task_id=str(context.task_id),
                commit=False,
            )
            relationship = crm.link_records(
                tenant_id=context.tenant_id,
                from_type="task",
                from_id=str(written["id"]),
                relationship_type="follows_up_with",
                to_type="contact",
                to_id=contact_id,
                source="mission_composition:followup",
            )
            verified = crm.read_record(
                tenant_id=context.tenant_id,
                record_type="task",
                record_id=str(written["id"]),
            )
            if verified is None or str(verified.get("related_id") or "") != contact_id:
                raise ValueError("sales.create_followup_task read-back verification failed")
            operation = "unchanged" if existing == written else ("updated" if existing else "created")
            tasks.append(
                {
                    **written,
                    "prospect_id": contact_id,
                    "operation": operation,
                    "readback_verified": True,
                    "relationship_id": str(relationship["id"]),
                }
            )
            readback.append(
                {
                    "record_type": "task",
                    "record_id": str(written["id"]),
                    "prospect_id": contact_id,
                    "verified": True,
                }
            )
            relationship_ids.append(str(relationship["id"]))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    changed = [str(item["id"]) for item in tasks]
    output = {
        "follow_up_tasks": tasks,
        "crm_readback_records": readback,
        "relationship_ids": relationship_ids,
        "persisted_count": len(tasks),
        "readback_verified_count": len(readback),
        "executed_at": execution_time.isoformat(),
    }
    summary = f"Created and read-back verified {len(tasks)} tenant CRM follow-up task(s)."
    return ActionResult(
        action="sales.create_followup_task",
        provider="local_sales",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.create_followup_task",
                provider="local_sales",
                summary=summary,
                payload=output,
                inspected=[str(item["prospect_id"]) for item in tasks],
                changed=changed,
                side_effect_class=SideEffectClass.INTERNAL_WRITE,
            )
        ],
        records_inspected=[str(item["prospect_id"]) for item in tasks],
        records_changed=changed,
        summary=summary,
        confidence=1.0,
    )
