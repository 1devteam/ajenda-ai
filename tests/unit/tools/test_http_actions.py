from __future__ import annotations

import pytest

from backend.services.tools.http_actions import validate_safe_http_url


def test_http_url_validation_allows_public_https_with_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))]
    )

    assert (
        validate_safe_http_url("https://example.com/path", allowed_hosts=["example.com"]) == "https://example.com/path"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://localhost/status",
        "https://service.local/status",
        "https://internal-api.example.com/status",
        "https://127.0.0.1/status",
        "https://10.1.2.3/status",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_http_url_validation_blocks_internal_targets(url: str) -> None:
    with pytest.raises(ValueError, match=r"http\.request"):
        validate_safe_http_url(url)


def test_http_url_validation_blocks_private_dns_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("10.0.0.4", 443))])

    with pytest.raises(ValueError, match="private DNS"):
        validate_safe_http_url("https://example.com")


def test_calendar_create_event_is_observable_by_read() -> None:
    import uuid

    from backend.services.tools.action_registry import get_default_action_registry
    from backend.services.tools.local_calendar import reset_default_local_calendar_provider
    from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation

    reset_default_local_calendar_provider()
    registry = get_default_action_registry(rebuild=True)
    context = ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )

    create_result = registry.invoke(
        ToolInvocation(
            action="calendar.create_event",
            input={
                "calendar_id": "primary",
                "title": "Discovery Call",
                "start": "2026-06-05T10:00:00Z",
                "end": "2026-06-05T10:30:00Z",
            },
        ),
        context,
    )
    read_result = registry.invoke(
        ToolInvocation(action="calendar.read", input={"calendar_id": "primary"}),
        context,
    )

    assert create_result.records_changed == ["evt-1"]
    assert read_result.output["count"] == 1
    assert read_result.output["events"][0]["title"] == "Discovery Call"


def test_calendar_read_honors_start_and_end_windows() -> None:
    import uuid

    from backend.services.tools.action_registry import get_default_action_registry
    from backend.services.tools.local_calendar import reset_default_local_calendar_provider
    from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation

    tenant_id = str(uuid.uuid4())
    reset_default_local_calendar_provider(
        {
            tenant_id: {
                "primary": [
                    {
                        "id": "evt-before",
                        "calendar_id": "primary",
                        "title": "Before",
                        "start": "2026-06-05T08:00:00Z",
                        "end": "2026-06-05T08:30:00Z",
                    },
                    {
                        "id": "evt-window",
                        "calendar_id": "primary",
                        "title": "In Window",
                        "start": "2026-06-05T10:00:00Z",
                        "end": "2026-06-05T10:30:00Z",
                    },
                    {
                        "id": "evt-after",
                        "calendar_id": "primary",
                        "title": "After",
                        "start": "2026-06-05T12:00:00Z",
                        "end": "2026-06-05T12:30:00Z",
                    },
                ]
            }
        }
    )
    registry = get_default_action_registry(rebuild=True)
    context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )

    result = registry.invoke(
        ToolInvocation(
            action="calendar.read",
            input={
                "calendar_id": "primary",
                "start": "2026-06-05T09:00:00Z",
                "end": "2026-06-05T11:00:00Z",
            },
        ),
        context,
    )

    assert result.output["count"] == 1
    assert result.output["events"][0]["id"] == "evt-window"


def test_webhook_dispatch_derives_stable_event_id_from_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import uuid

    from backend.services.tools.action_registry import get_default_action_registry
    from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation
    from backend.services.webhook_dispatch import WebhookDispatchResult

    captured_event_ids: list[uuid.UUID] = []

    class Session:
        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    class Service:
        def __init__(self, session: Session) -> None:
            self.session = session

        def dispatch_event(self, **kwargs):
            captured_event_ids.append(kwargs["event_id"])
            return [
                WebhookDispatchResult(
                    delivery_id=uuid.uuid4(),
                    succeeded=True,
                    http_status=200,
                )
            ]

    monkeypatch.setattr("backend.services.tools.webhook_actions.WebhookDispatchService", Service)

    tenant_id = str(uuid.uuid4())
    task_id = uuid.uuid4()
    context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=task_id,
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
        session_factory=Session,
    )
    registry = get_default_action_registry(rebuild=True)
    invocation = ToolInvocation(
        action="webhook.dispatch",
        idempotency_key="stable-key",
        input={"event_type": "task.completed", "payload": {"ok": True}},
    )

    first = registry.invoke(invocation, context)
    second = registry.invoke(invocation, context)

    assert captured_event_ids[0] == captured_event_ids[1]
    assert first.output["event_id"] == second.output["event_id"] == str(captured_event_ids[0])


def test_calendar_read_normalizes_offset_times_before_window_filtering() -> None:
    import uuid

    from backend.services.tools.action_registry import get_default_action_registry
    from backend.services.tools.local_calendar import reset_default_local_calendar_provider
    from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation

    tenant_id = str(uuid.uuid4())
    reset_default_local_calendar_provider(
        {
            tenant_id: {
                "primary": [
                    {
                        "id": "evt-before-window",
                        "calendar_id": "primary",
                        "title": "Before window",
                        "start": "2026-06-05T10:00:00-05:00",
                        "end": "2026-06-05T10:30:00-05:00",
                    },
                    {
                        "id": "evt-in-window",
                        "calendar_id": "primary",
                        "title": "In window",
                        "start": "2026-06-05T07:30:00-05:00",
                        "end": "2026-06-05T08:30:00-05:00",
                    },
                ]
            }
        }
    )
    context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=None,
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )
    registry = get_default_action_registry(rebuild=True)

    result = registry.invoke(
        ToolInvocation(
            action="calendar.read",
            input={
                "calendar_id": "primary",
                "start": "2026-06-05T12:00:00Z",
                "end": "2026-06-05T14:00:00Z",
            },
        ),
        context,
    )

    assert [event["id"] for event in result.output["events"]] == ["evt-in-window"]
