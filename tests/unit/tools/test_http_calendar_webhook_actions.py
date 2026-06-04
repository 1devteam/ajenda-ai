from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from backend.services.tools.calendar_actions import calendar_create_event, calendar_read
from backend.services.tools.http_actions import http_request
from backend.services.tools.local_calendar import LocalCalendarProvider
from backend.services.tools.schemas import ActionExecutionContext
from backend.services.tools.webhook_actions import webhook_dispatch


def _context(**extras: Any) -> ActionExecutionContext:
    return ActionExecutionContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-tools",
        lease_id=str(uuid.uuid4()),
        session_factory=lambda: SimpleNamespace(commit=lambda: None, rollback=lambda: None, close=lambda: None),
        extras=extras,
    )


def test_http_request_uses_injected_client_and_returns_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    context = _context()
    context.http_client = client

    result = http_request({"method": "GET", "url": "https://example.com/status"}, context)

    assert result.action == "http.request"
    assert result.side_effect_class == "external_read"
    assert result.output["http_status"] == 200
    assert result.evidence[0].evidence_source == "tool.invoke.http.request"


def test_http_request_rejects_private_loopback_ip() -> None:
    with pytest.raises(ValueError, match="private or loopback"):
        http_request({"method": "GET", "url": "http://127.0.0.1/internal"}, _context())


def test_calendar_actions_use_local_provider() -> None:
    provider = LocalCalendarProvider()
    context = _context(calendar_provider=provider)

    created = calendar_create_event(
        {
            "title": "Discovery Call",
            "start_at": "2026-06-05T10:00:00Z",
            "end_at": "2026-06-05T10:30:00Z",
            "attendees": ["buyer@example.com"],
        },
        context,
    )
    listed = calendar_read({"calendar_id": "default"}, context)

    assert created.side_effect_class == "internal_write"
    assert listed.output["count"] == 1
    assert listed.output["events"][0]["title"] == "Discovery Call"


def test_webhook_dispatch_reuses_webhook_service(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeWebhookDispatchService:
        def __init__(self, session: Any) -> None:
            self.session = session

        def dispatch_event(self, **kwargs: Any) -> list[Any]:
            calls.append(kwargs)
            return [SimpleNamespace(delivery_id=uuid.uuid4(), succeeded=True, http_status=204, error=None)]

    monkeypatch.setattr("backend.services.tools.webhook_actions.WebhookDispatchService", FakeWebhookDispatchService)
    context = _context()

    result = webhook_dispatch({"event_type": "task.completed", "payload": {"task_id": "t1"}}, context)

    assert calls[0]["event_type"] == "task.completed"
    assert result.action == "webhook.dispatch"
    assert result.side_effect_class == "external_send"
    assert result.output["delivery_count"] == 1
