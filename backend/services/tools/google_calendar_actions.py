"""Google Calendar read-only actions via governed external_read_provider credentials."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode

from pydantic import BaseModel, ConfigDict, Field

from backend.services.network_egress import get_default_network_egress_authority
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.provider_read_actions import PROVIDER_EXTERNAL_READ_PROVIDER
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    RuntimeCredentialMaterial,
    SideEffectClass,
    ToolInvocation,
)

GOOGLE_CALENDAR_EVENTS_READ_ACTION = "google_calendar.events_read"
GOOGLE_CALENDAR_API_HOST = "www.googleapis.com"


class GoogleCalendarEventsReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_id: str = Field(default="primary", min_length=1, max_length=160)
    start: str | None = Field(default=None, max_length=80)
    end: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=10, ge=1, le=50)


def _credential_secret(material: RuntimeCredentialMaterial | dict[str, Any] | None) -> str | None:
    if material is None:
        return None
    if isinstance(material, dict):
        secret = material.get("secret_value")
        return str(secret) if isinstance(secret, str) and secret else None
    return material.secret_value


def _get_runtime_credential(
    ctx: ActionRuntimeContext,
    *,
    action: str,
    aliases: tuple[str, ...] = (),
) -> RuntimeCredentialMaterial | dict[str, Any] | None:
    for key in (action, *aliases):
        if key in ctx.runtime_credentials:
            return ctx.runtime_credentials[key]
    return None


def _trusted_hosts(material: RuntimeCredentialMaterial | dict[str, Any] | None) -> tuple[str, ...]:
    if material is None:
        return (GOOGLE_CALENDAR_API_HOST,)
    if isinstance(material, dict):
        raw_hosts = material.get("trusted_destination_hosts")
        if raw_hosts:
            return tuple(str(host) for host in raw_hosts)
        return (GOOGLE_CALENDAR_API_HOST,)
    if material.trusted_destination_hosts:
        return material.trusted_destination_hosts
    return (GOOGLE_CALENDAR_API_HOST,)


def _events_url(*, calendar_id: str, limit: int, start: str | None, end: str | None) -> str:
    encoded_calendar = quote(calendar_id.strip(), safe="")
    params: dict[str, str] = {
        "maxResults": str(limit),
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    if start and start.strip():
        params["timeMin"] = start.strip()
    if end and end.strip():
        params["timeMax"] = end.strip()
    query = urlencode(params)
    return f"https://{GOOGLE_CALENDAR_API_HOST}/calendar/v3/calendars/{encoded_calendar}/events?{query}"


def _simulated_events() -> list[dict[str, Any]]:
    return [
        {
            "id": "sim-gcal-1",
            "summary": "Simulated calendar event",
            "start": {"dateTime": "2026-06-27T10:00:00Z"},
            "end": {"dateTime": "2026-06-27T11:00:00Z"},
        }
    ]


def google_calendar_events_read(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = GoogleCalendarEventsReadInput.model_validate(invocation.input)
    credential = _get_runtime_credential(
        context,
        action=invocation.action,
        aliases=(GOOGLE_CALENDAR_EVENTS_READ_ACTION, "provider.external_read", PROVIDER_EXTERNAL_READ_PROVIDER),
    )
    secret = _credential_secret(credential)
    events: list[dict[str, Any]]
    real = False
    status_code: int | None = None

    if secret:
        url = _events_url(
            calendar_id=payload.calendar_id,
            limit=payload.limit,
            start=payload.start,
            end=payload.end,
        )
        headers = {"Authorization": f"Bearer {secret}"}
        try:
            _destination, response = get_default_network_egress_authority().request(
                method="GET",
                url=url,
                headers=headers,
                json_body=None,
                allowed_hosts=list(_trusted_hosts(credential)),
                action_name=GOOGLE_CALENDAR_EVENTS_READ_ACTION,
                timeout_seconds=15.0,
            )
            status_code = response.status_code
            if not 200 <= response.status_code < 300:
                raise ValueError(f"Google Calendar API returned HTTP {response.status_code}")
            parsed = json.loads(response.body_text or "{}")
            if not isinstance(parsed, dict):
                raise ValueError("Google Calendar API returned non-object events payload")
            raw_items = parsed.get("items")
            if not isinstance(raw_items, list):
                raise ValueError("Google Calendar API response missing items list")
            events = [item for item in raw_items if isinstance(item, dict)]
            real = True
        except Exception as exc:
            raise ValueError(f"Google Calendar events read failed on credentialed path: {exc}") from exc
    else:
        events = _simulated_events()

    output = {
        "calendar_id": payload.calendar_id,
        "events": events,
        "count": len(events),
        "real": real,
        "source": "google_calendar_api" if real else "simulated",
    }
    if status_code is not None:
        output["real_response"] = {"status_code": status_code}

    summary = (
        f"Read {len(events)} Google Calendar event(s) via API"
        if real
        else f"Read {len(events)} simulated calendar event(s); no credential"
    )
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source=f"tool.invoke.{GOOGLE_CALENDAR_EVENTS_READ_ACTION}",
        action_name=GOOGLE_CALENDAR_EVENTS_READ_ACTION,
        tool_provider=PROVIDER_EXTERNAL_READ_PROVIDER,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=output,
        records_inspected=[str(item.get("id", "")) for item in events if item.get("id")],
        side_effect_class=SideEffectClass.EXTERNAL_READ,
    )
    return ActionResult(
        action=GOOGLE_CALENDAR_EVENTS_READ_ACTION,
        provider=PROVIDER_EXTERNAL_READ_PROVIDER,
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output=output,
        evidence=[evidence],
        summary=summary,
    )


def register_google_calendar_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name=GOOGLE_CALENDAR_EVENTS_READ_ACTION,
            handler=google_calendar_events_read,
            provider=PROVIDER_EXTERNAL_READ_PROVIDER,
            input_model=GoogleCalendarEventsReadInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )