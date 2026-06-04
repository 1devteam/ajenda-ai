from __future__ import annotations

import uuid
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    event_id: str
    tenant_id: str
    calendar_id: str
    title: str
    start_at: str
    end_at: str
    attendees: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "tenant_id": self.tenant_id,
            "calendar_id": self.calendar_id,
            "title": self.title,
            "start_at": self.start_at,
            "end_at": self.end_at,
            "attendees": list(self.attendees),
            "metadata": deepcopy(self.metadata),
        }


@dataclass(slots=True)
class LocalCalendarProvider:
    _events: dict[str, dict[str, list[CalendarEvent]]] = field(default_factory=lambda: defaultdict(dict))

    def list_events(self, *, tenant_id: str, calendar_id: str, limit: int) -> list[CalendarEvent]:
        if limit < 1 or limit > 100:
            raise ValueError("calendar read limit must be between 1 and 100")
        return list(self._events.get(tenant_id, {}).get(calendar_id, []))[:limit]

    def create_event(
        self,
        *,
        tenant_id: str,
        calendar_id: str,
        title: str,
        start_at: str,
        end_at: str,
        attendees: list[str],
        metadata: dict[str, Any],
    ) -> CalendarEvent:
        event = CalendarEvent(
            event_id=f"local-calendar-{uuid.uuid4()}",
            tenant_id=tenant_id,
            calendar_id=calendar_id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            attendees=tuple(attendees),
            metadata=deepcopy(metadata),
        )
        self._events.setdefault(tenant_id, {}).setdefault(calendar_id, []).append(event)
        return event


_DEFAULT_CALENDAR_PROVIDER = LocalCalendarProvider()


def default_local_calendar_provider() -> LocalCalendarProvider:
    return _DEFAULT_CALENDAR_PROVIDER
