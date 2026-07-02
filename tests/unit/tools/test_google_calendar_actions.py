from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.services.tools.action_registry import ActionRegistry
from backend.services.tools.google_calendar_actions import register_google_calendar_actions
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
    )


def test_google_calendar_events_read_simulated_without_credential() -> None:
    registry = ActionRegistry()
    register_google_calendar_actions(registry)
    result = registry.invoke(
        ToolInvocation(action="google_calendar.events_read", input={"calendar_id": "primary"}),
        _context(),
    )

    assert result.output["real"] is False
    assert result.output["events"][0]["id"] == "sim-gcal-1"
    assert result.side_effect_class.value == "external_read"


def test_google_calendar_events_read_uses_api_with_runtime_credential() -> None:
    registry = ActionRegistry()
    register_google_calendar_actions(registry)
    handler = registry.get("google_calendar.events_read").handler
    context = _context()
    context.runtime_credentials = {
        "google_calendar.events_read": {
            "secret_value": "google-calendar-token",
            "trusted_destination_hosts": ["www.googleapis.com"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://www.googleapis.com/calendar/v3/calendars/primary/events",
        connect_url="https://1.2.3.4/calendar/v3/calendars/primary/events",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="www.googleapis.com",
        host_header="www.googleapis.com",
    )
    response = NetworkEgressResponse(
        status_code=200,
        headers={},
        body_text='{"items":[{"id":"evt-live-1","summary":"Standup"}]}',
        body_truncated=False,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.google_calendar_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        result = handler(
            ToolInvocation(action="google_calendar.events_read", input={"calendar_id": "primary", "limit": 5}),
            context,
        )

    assert result.output["real"] is True
    assert result.output["events"][0]["id"] == "evt-live-1"
    assert authority.request.call_args.kwargs["headers"]["Authorization"] == "Bearer google-calendar-token"


def test_google_calendar_events_read_fail_closed_on_credentialed_api_error() -> None:
    registry = ActionRegistry()
    register_google_calendar_actions(registry)
    handler = registry.get("google_calendar.events_read").handler
    context = _context()
    context.runtime_credentials = {
        "google_calendar.events_read": {
            "secret_value": "google-calendar-token",
            "trusted_destination_hosts": ["www.googleapis.com"],
        }
    }
    authority = MagicMock()
    authority.request.side_effect = RuntimeError("egress blocked")

    with patch(
        "backend.services.tools.google_calendar_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        try:
            handler(ToolInvocation(action="google_calendar.events_read", input={}), context)
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "credentialed path" in str(exc)
