from __future__ import annotations

from typing import Any

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.local_calendar import LocalCalendarProvider, default_local_calendar_provider
from backend.services.tools.schemas import (
    ActionExecutionContext,
    ActionResult,
    CalendarCreateEventInput,
    CalendarReadInput,
    EvidenceItem,
)


def _provider(context: ActionExecutionContext) -> LocalCalendarProvider:
    candidate = context.extras.get("calendar_provider")
    if isinstance(candidate, LocalCalendarProvider):
        return candidate
    return default_local_calendar_provider()


def calendar_read(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    parsed = CalendarReadInput.model_validate(payload)
    events = _provider(context).list_events(
        tenant_id=context.tenant_id, calendar_id=parsed.calendar_id, limit=parsed.limit
    )
    output = {"calendar_id": parsed.calendar_id, "count": len(events), "events": [event.to_dict() for event in events]}
    return ActionResult(
        action="calendar.read",
        output=output,
        evidence=[
            EvidenceItem(
                evidence_type="action_result",
                evidence_source="tool.invoke.calendar.read",
                summary=f"Read {len(events)} calendar event(s).",
                structured_payload=output,
                confidence=1.0,
                trust_signal={"provider": "local_calendar"},
            )
        ],
    )


def calendar_create_event(payload: dict[str, Any], context: ActionExecutionContext) -> ActionResult:
    parsed = CalendarCreateEventInput.model_validate(payload)
    event = _provider(context).create_event(
        tenant_id=context.tenant_id,
        calendar_id=parsed.calendar_id,
        title=parsed.title,
        start_at=parsed.start_at,
        end_at=parsed.end_at,
        attendees=parsed.attendees,
        metadata=parsed.metadata,
    )
    output = {"event": event.to_dict()}
    return ActionResult(
        action="calendar.create_event",
        side_effect_class="internal_write",
        output=output,
        evidence=[
            EvidenceItem(
                evidence_type="action_result",
                evidence_source="tool.invoke.calendar.create_event",
                summary="Created local calendar event.",
                structured_payload=output,
                confidence=1.0,
                trust_signal={"provider": "local_calendar"},
            )
        ],
    )


def register_calendar_actions(registry: ActionRegistry) -> None:
    registry.register(ActionDefinition(name="calendar.read", handler=calendar_read))
    registry.register(
        ActionDefinition(
            name="calendar.create_event", handler=calendar_create_event, side_effect_class="internal_write"
        )
    )
