from __future__ import annotations

import uuid
from contextlib import nullcontext
from datetime import UTC, datetime

from backend.services.ui_runtime_causal_trace import (
    BrowserInteractionEvent,
    UIInteractionTraceService,
)


class _Session:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.commits = 0

    def add(self, value: object) -> None:
        self.events.append(value)

    def flush(self) -> None:
        return None

    def refresh(self, value: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def begin_nested(self):
        return nullcontext()


class _AuditRepository:
    def __init__(self, session: _Session) -> None:
        self._session = session

    def get_for_tenant(self, *, event_id: uuid.UUID, tenant_id: str):
        return next(
            (
                event
                for event in self._session.events
                if getattr(event, "id", None) == event_id and getattr(event, "tenant_id", None) == tenant_id
            ),
            None,
        )


def test_browser_event_acknowledges_only_after_commit_and_retries_idempotently() -> None:
    session = _Session()
    service = UIInteractionTraceService(session, audit_repository=_AuditRepository(session))
    local_id = uuid.uuid4()
    event = BrowserInteractionEvent(
        event_id=local_id,
        local_interaction_id=local_id,
        action_id="credential.linkedin.oauth.connect",
        phase="ui.action_clicked",
        producer_sequence=1,
        occurred_at=datetime(2026, 10, 21, tzinfo=UTC),
    )

    first = service.accept_browser_event(tenant_id="tenant-a", actor_id="human:a", event=event)
    retry = service.accept_browser_event(tenant_id="tenant-a", actor_id="human:a", event=event)

    assert first.acknowledgement == "persisted"
    assert session.commits == 1
    assert retry.duplicate is True
    assert retry.server_interaction_id == first.server_interaction_id
    assert len(session.events) == 1


def test_server_interaction_requires_same_tenant_persisted_browser_association() -> None:
    session = _Session()
    service = UIInteractionTraceService(session, audit_repository=_AuditRepository(session))
    local_id = uuid.uuid4()
    receipt = service.accept_browser_event(
        tenant_id="tenant-a",
        actor_id="human:a",
        event=BrowserInteractionEvent(
            event_id=local_id,
            local_interaction_id=local_id,
            action_id="credential.linkedin.oauth.connect",
            phase="ui.action_clicked",
            producer_sequence=1,
            occurred_at=datetime(2026, 10, 21, tzinfo=UTC),
        ),
    )

    assert (
        service.resolve_server_interaction(
            tenant_id="tenant-a",
            local_interaction_id=local_id,
            server_interaction_id=receipt.server_interaction_id,
        )
        == receipt.server_interaction_id
    )
    # The same opaque client UUID cannot join another tenant's trace.
    fresh = service.resolve_server_interaction(
        tenant_id="tenant-b",
        local_interaction_id=local_id,
        server_interaction_id=None,
    )
    assert fresh != receipt.server_interaction_id


def test_server_observation_failure_cannot_become_oauth_authority() -> None:
    class _FailingObservationSession(_Session):
        def begin_nested(self):
            raise RuntimeError("audit ledger unavailable")

    session = _FailingObservationSession()
    service = UIInteractionTraceService(session, audit_repository=_AuditRepository(session))

    observed = service.append_server_event(
        tenant_id="tenant-a",
        actor_id="human:a",
        interaction_id=uuid.uuid4(),
        local_interaction_id=None,
        action_id="credential.linkedin.oauth.connect",
        phase="api.request_received",
        outcome_code="ROUTE_MATCHED",
    )

    assert observed is None
    assert session.commits == 0
