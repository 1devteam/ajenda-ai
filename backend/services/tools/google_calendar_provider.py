"""Google Calendar provider adapter contract and OAuth scopes.

Connector OAuth only — identity login must never request these scopes.
"""

from __future__ import annotations

from typing import Any

from backend.services.tools.calendar_provider import CalendarProvider
from backend.services.tools.external_credentials import ExternalCredentialReference, ExternalProviderName

# Product connector consent matches Google Cloud OAuth client scopes in use.
GOOGLE_CALENDAR_READ_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
GOOGLE_CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class GoogleCalendarProvider(CalendarProvider):
    """Contract shell for a future Google Calendar provider."""

    def __init__(self, *, credential: ExternalCredentialReference) -> None:
        if credential.provider != ExternalProviderName.GOOGLE_CALENDAR:
            raise ValueError("GoogleCalendarProvider requires google_calendar credentials")
        self.credential = credential

    def read_events(
        self,
        *,
        tenant_id: str,
        calendar_id: str,
        limit: int = 10,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read Google Calendar events.

        Deferred until the credential resolver and Google API client are added.
        """

        self._validate_tenant(tenant_id)
        raise NotImplementedError("Google Calendar read provider is not implemented")

    def create_event(
        self,
        *,
        tenant_id: str,
        calendar_id: str,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a Google Calendar event.

        Deferred until the credential resolver and Google API client are added.
        """

        self._validate_tenant(tenant_id)
        raise NotImplementedError("Google Calendar create provider is not implemented")

    def _validate_tenant(self, tenant_id: str) -> None:
        if tenant_id != self.credential.tenant_id:
            raise ValueError("credential tenant_id does not match provider call tenant_id")


def required_google_calendar_scopes(*, write: bool = True) -> tuple[str, ...]:
    """Scopes requested for Calendar connector OAuth.

    Product default is ``calendar.events`` (view/edit events), matching the
    Ajenda Google OAuth client consent configuration.
    """

    if write:
        return (GOOGLE_CALENDAR_EVENTS_SCOPE,)
    return (GOOGLE_CALENDAR_READ_SCOPE,)


def recognized_google_calendar_scopes() -> tuple[str, ...]:
    """Scopes that identify a stored secret as a calendar OAuth bundle."""

    return (GOOGLE_CALENDAR_EVENTS_SCOPE, GOOGLE_CALENDAR_READ_SCOPE)
