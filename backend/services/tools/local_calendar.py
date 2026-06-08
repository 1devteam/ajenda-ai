from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.services.tools.calendar_provider import CalendarProvider


@dataclass(slots=True)
class LocalCalendarProvider(CalendarProvider):
    """Tenant-scoped deterministic proof provider, not durable calendar storage."""

    seed_events: dict[str, dict[str, list[dict[str, Any]]]] | None = None
    _events: dict[str, dict[str, list[dict[str, Any]]]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.reset(self.seed_events)

    def reset(self, seed_events: dict[str, dict[str, list[dict[str, Any]]]] | None = None) -> None:
        self._events = deepcopy(seed_events if seed_events is not None else {})

    def read_events(
        self,
        *,
        tenant_id: str,
        calendar_id: str,
        limit: int = 10,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        events = self._events.setdefault(tenant_id, {}).setdefault(calendar_id, [])
        window_start = _parse_calendar_timestamp(start) if start is not None else None
        window_end = _parse_calendar_timestamp(end) if end is not None else None
        filtered = [
            event
            for event in events
            if _event_overlaps_window(
                event=event,
                window_start=window_start,
                window_end=window_end,
            )
        ]
        return deepcopy(filtered[:limit])

    def create_event(self, *, tenant_id: str, calendar_id: str, event: dict[str, Any]) -> dict[str, Any]:
        events = self._events.setdefault(tenant_id, {}).setdefault(calendar_id, [])
        event_id = f"evt-{len(events) + 1}"
        stored = {"id": event_id, **deepcopy(event)}
        events.append(stored)
        return deepcopy(stored)


def _parse_calendar_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _event_overlaps_window(
    *,
    event: dict[str, Any],
    window_start: datetime | None,
    window_end: datetime | None,
) -> bool:
    if window_start is None and window_end is None:
        return True

    event_start_raw = event.get("start")
    event_end_raw = event.get("end")
    if not isinstance(event_start_raw, str) or not isinstance(event_end_raw, str):
        return False

    event_start = _parse_calendar_timestamp(event_start_raw)
    event_end = _parse_calendar_timestamp(event_end_raw)

    if window_start is not None and event_end < window_start:
        return False
    if window_end is not None and event_start > window_end:
        return False
    return True


_DEFAULT_LOCAL_CALENDAR_PROVIDER = LocalCalendarProvider()


def default_local_calendar_provider() -> LocalCalendarProvider:
    return _DEFAULT_LOCAL_CALENDAR_PROVIDER


def reset_default_local_calendar_provider(
    seed_events: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
) -> None:
    _DEFAULT_LOCAL_CALENDAR_PROVIDER.reset(seed_events)
