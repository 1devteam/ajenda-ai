"""Unit tests for admin route actor attribution.

Verifies that _get_actor() reads principal.subject_id (the canonical
field on the Principal dataclass) rather than the non-existent
principal.subject attribute, which previously caused every authenticated
admin call to record "unknown_admin" in governance events.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from starlette.requests import Request
from starlette.testclient import TestClient

from backend.api.routes.admin import _get_actor
from backend.auth.principal import MachinePrincipal, PrincipalType, UserPrincipal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(principal=None) -> Request:
    """Build a minimal Starlette Request with an optional principal on state."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v1/admin/tenants",
        "headers": [],
        "query_string": b"",
    }
    request = Request(scope)
    if principal is not None:
        request.state.principal = principal
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetActor:
    def test_returns_subject_id_for_user_principal(self):
        """Authenticated admin user: actor must be the real subject_id."""
        principal = UserPrincipal(
            subject_id="user-abc-123",
            tenant_id="tenant-xyz",
            principal_type=PrincipalType.USER,
            roles=("admin",),
            email="admin@example.com",
        )
        request = _make_request(principal=principal)
        actor = _get_actor(request)
        assert actor == "user-abc-123", (
            "_get_actor must return principal.subject_id, not 'unknown_admin'"
        )

    def test_returns_subject_id_for_machine_principal(self):
        """Machine principal (service account): actor must be the real subject_id."""
        principal = MachinePrincipal(
            subject_id="svc-account-456",
            tenant_id="tenant-xyz",
            principal_type=PrincipalType.MACHINE,
            roles=("admin",),
            key_id="key-789",
        )
        request = _make_request(principal=principal)
        actor = _get_actor(request)
        assert actor == "svc-account-456"

    def test_returns_unknown_admin_when_no_principal(self):
        """No principal on request state: fallback to 'unknown_admin' is acceptable."""
        request = _make_request(principal=None)
        actor = _get_actor(request)
        assert actor == "unknown_admin"

    def test_does_not_return_unknown_admin_for_authenticated_call(self):
        """Regression guard: a fully authenticated call must NEVER produce 'unknown_admin'."""
        principal = UserPrincipal(
            subject_id="operator-obex",
            tenant_id="tenant-1",
            principal_type=PrincipalType.USER,
            roles=("admin",),
        )
        request = _make_request(principal=principal)
        actor = _get_actor(request)
        assert actor != "unknown_admin", (
            "Authenticated admin calls must not fall back to 'unknown_admin'. "
            "This indicates _get_actor is reading a non-existent attribute."
        )

    def test_subject_id_is_propagated_not_subject(self):
        """Explicit guard: principal has subject_id but NOT subject — actor must still resolve."""
        principal = UserPrincipal(
            subject_id="real-operator-id",
            tenant_id="tenant-1",
            principal_type=PrincipalType.USER,
            roles=("admin",),
        )
        # Confirm the Principal dataclass does NOT have a 'subject' attribute
        assert not hasattr(principal, "subject"), (
            "Principal must not expose 'subject' — only 'subject_id'. "
            "If this assertion fails, the dataclass was changed and the test needs updating."
        )
        request = _make_request(principal=principal)
        assert _get_actor(request) == "real-operator-id"
