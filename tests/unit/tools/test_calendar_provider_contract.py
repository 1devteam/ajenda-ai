from __future__ import annotations

from backend.services.tools.calendar_provider import CalendarProvider
from backend.services.tools.local_calendar import LocalCalendarProvider


def test_local_calendar_provider_satisfies_calendar_provider_contract() -> None:
    provider: CalendarProvider = LocalCalendarProvider()

    created = provider.create_event(
        tenant_id="tenant-1",
        calendar_id="primary",
        event={
            "calendar_id": "primary",
            "title": "Demo",
            "start": "2026-06-08T10:00:00Z",
            "end": "2026-06-08T10:30:00Z",
            "attendees": [],
            "description": None,
        },
    )
    events = provider.read_events(
        tenant_id="tenant-1",
        calendar_id="primary",
        start="2026-06-08T09:00:00Z",
        end="2026-06-08T11:00:00Z",
    )

    assert created["id"] == "evt-1"
    assert events == [created]


def test_local_calendar_provider_is_tenant_scoped() -> None:
    provider: CalendarProvider = LocalCalendarProvider()

    provider.create_event(
        tenant_id="tenant-1",
        calendar_id="primary",
        event={
            "calendar_id": "primary",
            "title": "Tenant 1",
            "start": "2026-06-08T10:00:00Z",
            "end": "2026-06-08T10:30:00Z",
            "attendees": [],
            "description": None,
        },
    )

    assert provider.read_events(tenant_id="tenant-2", calendar_id="primary") == []
