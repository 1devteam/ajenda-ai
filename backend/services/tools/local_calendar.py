from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LocalCalendarProvider:
    """Tenant-scoped deterministic proof provider, not durable calendar storage."""

    seed_events: dict[str, dict[str, list[dict[str, Any]]]] | None = None
    _events: dict[str, dict[str, list[dict[str, Any]]]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.reset(self.seed_events)

    def reset(self, seed_events: dict[str, dict[str, list[dict[str, Any]]]] | None = None) -> None:
        self._events = deepcopy(seed_events if seed_events is not None else {})

    def read_events(self, *, tenant_id: str, calendar_id: str, limit: int = 10) -> list[dict[str, Any]]:
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        return deepcopy(self._events.setdefault(tenant_id, {}).setdefault(calendar_id, [])[:limit])

    def create_event(self, *, tenant_id: str, calendar_id: str, event: dict[str, Any]) -> dict[str, Any]:
        events = self._events.setdefault(tenant_id, {}).setdefault(calendar_id, [])
        event_id = f"evt-{len(events) + 1}"
        stored = {"id": event_id, **deepcopy(event)}
        events.append(stored)
        return deepcopy(stored)
