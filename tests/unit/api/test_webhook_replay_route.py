from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.api.routes import webhooks as webhooks_route


class _FakeService:
    def __init__(self, db):  # type: ignore[no-untyped-def]
        self.db = db

    def replay_delivery(self, **kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            delivery_id=uuid.uuid4(),
            succeeded=True,
            http_status=200,
            error=None,
        )


class _FakeAuditRepo:
    def __init__(self, db):  # type: ignore[no-untyped-def]
        self.db = db
        self.events = []

    def append(self, event) -> None:  # type: ignore[no-untyped-def]
        self.events.append(event)


def test_replay_route_requires_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    request = SimpleNamespace(headers={}, state=SimpleNamespace(principal=None))
    db = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        webhooks_route.replay_webhook_delivery(
            endpoint_id=uuid.uuid4(),
            delivery_id=uuid.uuid4(),
            request=request,
            tenant_id=uuid.uuid4(),
            db=db,
        )
    assert "Idempotency-Key" in str(exc_info.value)


def test_replay_route_appends_audit_event(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_repo = _FakeAuditRepo(MagicMock())
    monkeypatch.setattr(webhooks_route, "WebhookDispatchService", _FakeService)
    monkeypatch.setattr(webhooks_route, "AuditEventRepository", lambda db: fake_repo)

    request = SimpleNamespace(
        headers={"Idempotency-Key": "replay-1"},
        state=SimpleNamespace(principal=SimpleNamespace(subject_id="user-1")),
    )
    db = MagicMock()
    response = webhooks_route.replay_webhook_delivery(
        endpoint_id=uuid.uuid4(),
        delivery_id=uuid.uuid4(),
        request=request,
        tenant_id=uuid.uuid4(),
        db=db,
    )

    assert response.status == "delivered"
    assert len(fake_repo.events) == 1
    assert fake_repo.events[0].action == "delivery_replay_requested"
