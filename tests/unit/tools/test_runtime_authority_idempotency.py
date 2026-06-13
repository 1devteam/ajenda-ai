from __future__ import annotations

import uuid
import types

import pytest

from backend.domain.enums import ExecutionTaskState
from backend.services.tools.runtime_authority import ToolRuntimeAuthority, ToolRuntimeAuthorityError


# Stub session factory that returns an object with a close method

def _stub_session_factory():
    class _Session:
        def close(self) -> None:
            pass
    return _Session()


def test_authorize_requires_idempotency_key_for_http_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP request actions with idempotency_required must include an idempotency key."""
    # Stub out capability validation to bypass capability/adapter checks for this test
    monkeypatch.setattr(
        "backend.services.tools.capability_validation.validate_capability_action_authority",
        lambda *args, **kwargs: None,
    )
    authority = ToolRuntimeAuthority()
    task = types.SimpleNamespace(
        tenant_id="tenant",
        id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        status=ExecutionTaskState.RUNNING.value,
        metadata_json={
            "tool_invocation": {
                "schema_version": 1,
                "action": "http.request",
                # intentionally omit idempotency_key
            }
        },
    )
    context = {
        "tenant_id": "tenant",
        "worker_id": "worker",
        "lease_id": "lease",
        "session_factory": _stub_session_factory,
    }
    with pytest.raises(ToolRuntimeAuthorityError, match="idempotency key required"):
        authority.authorize(task=task, context=context)


def test_authorize_allows_idempotency_key_for_http_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP request actions should succeed when an idempotency key is provided."""
    monkeypatch.setattr(
        "backend.services.tools.capability_validation.validate_capability_action_authority",
        lambda *args, **kwargs: None,
    )
    authority = ToolRuntimeAuthority()
    task = types.SimpleNamespace(
        tenant_id="tenant",
        id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        status=ExecutionTaskState.RUNNING.value,
        metadata_json={
            "tool_invocation": {
                "schema_version": 1,
                "action": "http.request",
                "idempotency_key": "abc123",
            }
        },
    )
    context = {
        "tenant_id": "tenant",
        "worker_id": "worker",
        "lease_id": "lease",
        "session_factory": _stub_session_factory,
    }
    invocation, action, side_effect_class = authority.authorize(task=task, context=context)
    assert invocation.idempotency_key == "abc123"
    assert action.name == "http.request"


def test_authorize_does_not_require_idempotency_for_non_idempotent_action(monkeypatch: pytest.MonkeyPatch) -> None:
    """Actions without idempotency_required should not require an idempotency key."""
    monkeypatch.setattr(
        "backend.services.tools.capability_validation.validate_capability_action_authority",
        lambda *args, **kwargs: None,
    )
    authority = ToolRuntimeAuthority()
    task = types.SimpleNamespace(
        tenant_id="tenant",
        id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        status=ExecutionTaskState.RUNNING.value,
        metadata_json={
            "tool_invocation": {
                "schema_version": 1,
                "action": "calendar.read",
                # no idempotency_key
            }
        },
    )
    context = {
        "tenant_id": "tenant",
        "worker_id": "worker",
        "lease_id": "lease",
        "session_factory": _stub_session_factory,
    }
    invocation, action, side_effect_class = authority.authorize(task=task, context=context)
    assert invocation.idempotency_key is None
    assert action.name == "calendar.read"
