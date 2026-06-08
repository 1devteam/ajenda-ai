"""Calendar provider contract for tool actions.

This module defines the provider boundary used by calendar tool actions.
It does not add real external providers or change tool.invoke runtime authority.
"""

from __future__ import annotations

from typing import Any, Protocol


class CalendarProvider(Protocol):
    """Provider boundary for calendar read and create operations."""

    def read_events(
        self,
        *,
        tenant_id: str,
        calendar_id: str,
        limit: int = 10,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read calendar events for one tenant/calendar window."""

    def create_event(
        self,
        *,
        tenant_id: str,
        calendar_id: str,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a calendar event and return the provider event payload."""
