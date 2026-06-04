from __future__ import annotations

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.local_calendar import LocalCalendarProvider, default_local_calendar_provider
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    CalendarCreateEventInput,
    CalendarReadInput,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
)


def _provider() -> LocalCalendarProvider:
    return default_local_calendar_provider()


def calendar_read(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = CalendarReadInput.model_validate(invocation.input)
    events = _provider().read_events(tenant_id=context.tenant_id, calendar_id=payload.calendar_id, limit=payload.limit)
    output = {"calendar_id": payload.calendar_id, "events": events, "count": len(events)}
    summary = f"Read {len(events)} event(s) from local calendar {payload.calendar_id}."
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.calendar.read",
        action_name="calendar.read",
        tool_provider="local_calendar",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=output,
        confidence=1.0,
        limitations=["local proof provider; not durable calendar storage"],
        provenance={"provider": "LocalCalendarProvider"},
        side_effect_class=SideEffectClass.NONE,
    )
    return ActionResult(
        action="calendar.read",
        provider="local_calendar",
        output=output,
        evidence=[evidence],
        summary=summary,
        confidence=1.0,
    )


def calendar_create_event(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = CalendarCreateEventInput.model_validate(invocation.input)
    event = _provider().create_event(
        tenant_id=context.tenant_id, calendar_id=payload.calendar_id, event=payload.model_dump(mode="json")
    )
    output = {"calendar_id": payload.calendar_id, "event": event}
    summary = f"Created local calendar event {event['id']} in {payload.calendar_id}."
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.calendar.create_event",
        action_name="calendar.create_event",
        tool_provider="local_calendar",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=output,
        records_changed=[event["id"]],
        confidence=1.0,
        limitations=["local proof provider; not durable calendar storage"],
        provenance={"provider": "LocalCalendarProvider"},
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
    )
    return ActionResult(
        action="calendar.create_event",
        provider="local_calendar",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        output=output,
        evidence=[evidence],
        records_changed=[event["id"]],
        summary=summary,
        confidence=1.0,
    )


def register_calendar_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="calendar.read", handler=calendar_read, provider="local_calendar", input_model=CalendarReadInput
        )
    )
    registry.register(
        ActionDefinition(
            name="calendar.create_event",
            handler=calendar_create_event,
            provider="local_calendar",
            input_model=CalendarCreateEventInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
