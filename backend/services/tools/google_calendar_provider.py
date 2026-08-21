"""Google Calendar provider adapter contract and OAuth scopes.

Connector OAuth only — identity login must never request these scopes.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode

from backend.services.network_egress import get_default_network_egress_authority
from backend.services.tools.calendar_provider import CalendarProvider
from backend.services.tools.credential_resolver import (
    CredentialResolutionError,
    CredentialResolver,
    EnvironmentCredentialResolver,
)
from backend.services.tools.external_credentials import ExternalCredentialReference, ExternalProviderName

# Product connector consent matches Google Cloud OAuth client scopes in use.
GOOGLE_CALENDAR_READ_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
GOOGLE_CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class GoogleCalendarProvider(CalendarProvider):
    """Tenant-scoped Google Calendar provider using governed network egress."""

    def __init__(
        self,
        *,
        credential: ExternalCredentialReference,
        resolver: CredentialResolver | None = None,
    ) -> None:
        if credential.provider != ExternalProviderName.GOOGLE_CALENDAR:
            raise ValueError("GoogleCalendarProvider requires google_calendar credentials")
        self.credential = credential
        self._resolver = resolver or EnvironmentCredentialResolver()

    def read_events(
        self,
        *,
        tenant_id: str,
        calendar_id: str,
        limit: int = 10,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_tenant(tenant_id)
        token = self._access_token()
        params: dict[str, str] = {
            "maxResults": str(max(1, min(limit, 50))),
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        if start and start.strip():
            params["timeMin"] = start.strip()
        if end and end.strip():
            params["timeMax"] = end.strip()
        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            f"{quote(calendar_id.strip(), safe='')}/events?{urlencode(params)}"
        )
        payload = self._request(method="GET", url=url, token=token)
        items = payload.get("items")
        if not isinstance(items, list):
            raise ValueError("Google Calendar API response missing items list")
        return [item for item in items if isinstance(item, dict)]

    def create_event(
        self,
        *,
        tenant_id: str,
        calendar_id: str,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_tenant(tenant_id)
        raise CredentialResolutionError(
            "Google Calendar event creation must use the governed tool.invoke authorization path"
        )

    def _access_token(self) -> str:
        try:
            resolved = self._resolver.resolve(self.credential)
        except CredentialResolutionError:
            raise
        except Exception as exc:
            raise CredentialResolutionError("Google Calendar credential resolution failed") from exc
        secret = resolved.secret_value.strip()
        if secret.startswith("{"):
            try:
                document = json.loads(secret)
            except json.JSONDecodeError as exc:
                raise CredentialResolutionError("Google Calendar credential JSON is invalid") from exc
            token = document.get("access_token") if isinstance(document, dict) else None
            if not isinstance(token, str) or not token.strip():
                raise CredentialResolutionError("Google Calendar credential JSON has no access_token")
            return token.strip()
        return secret

    @staticmethod
    def _request(*, method: str, url: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        _destination, response = get_default_network_egress_authority().request(
            method=method,
            url=url,
            headers={"Authorization": f"Bearer {token}"},
            json_body=body,
            allowed_hosts=["www.googleapis.com"],
            action_name="google_calendar.events_read" if method == "GET" else "calendar.create_event",
            timeout_seconds=15.0,
        )
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Google Calendar API returned HTTP {response.status_code}")
        try:
            payload = json.loads(response.body_text or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Google Calendar API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Google Calendar API returned a non-object payload")
        return payload

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
