from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from backend.services.tools import webhook_actions
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def test_webhook_dispatch_activates_tenant_session_before_service_call(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    session = MagicMock()
    events: list[str] = []

    def activate(_session, activated_tenant_id: str) -> None:
        assert _session is session
        assert activated_tenant_id == tenant_id
        events.append("tenant_session")

    class FakeWebhookDispatchService:
        def __init__(self, received_session) -> None:
            assert received_session is session
            events.append("service_init")

        def dispatch_event(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["tenant_id"] == uuid.UUID(tenant_id)
            events.append("dispatch")
            return []

    monkeypatch.setattr(webhook_actions, "activate_tenant_session", activate)
    monkeypatch.setattr(webhook_actions, "WebhookDispatchService", FakeWebhookDispatchService)

    invocation = ToolInvocation(
        action="webhook.dispatch",
        input={"event_type": "task.completed", "payload": {"task_id": "task-1"}},
    )
    context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
        session_factory=lambda: session,
    )

    result = webhook_actions.webhook_dispatch(invocation, context)

    assert events == ["tenant_session", "service_init", "dispatch"]
    assert result.output["delivery_count"] == 0
    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()
    session.close.assert_called_once_with()
