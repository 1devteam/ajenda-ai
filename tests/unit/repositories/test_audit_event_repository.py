from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from backend.domain.audit_event import AuditEvent
from backend.repositories.audit_event_repository import AuditEventRepository


def _event() -> AuditEvent:
    return AuditEvent(
        tenant_id=str(uuid.uuid4()),
        mission_id=None,
        category="test",
        action="test.action",
        actor="test:actor",
        details="test audit event",
        payload_json={},
    )


@patch("backend.repositories.audit_event_repository.activate_tenant_session")
def test_append_activates_event_tenant_before_persisting(mock_activate: MagicMock) -> None:
    session = MagicMock()
    event = _event()

    AuditEventRepository(session).append(event)

    mock_activate.assert_called_once_with(session, event.tenant_id)
    session.add.assert_called_once_with(event)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(event)


@patch("backend.repositories.audit_event_repository.activate_tenant_session")
def test_append_unflushed_activates_event_tenant_before_staging(mock_activate: MagicMock) -> None:
    session = MagicMock()
    event = _event()

    result = AuditEventRepository(session).append_unflushed(event)

    assert result is event
    mock_activate.assert_called_once_with(session, event.tenant_id)
    session.add.assert_called_once_with(event)
