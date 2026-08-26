from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.services.oidc_login_service import CustomerSessionResult, OidcLoginService


def _settings() -> Settings:
    return Settings.model_construct(
        env="test",
        oidc_login_enabled=True,
        session_signing_secret="s" * 48,
        session_access_ttl_seconds=3600,
        session_refresh_ttl_seconds=604800,
        auth_login_start_ip_limit_per_hour=100,
        auth_login_callback_ip_limit_per_hour=100,
        auth_login_callback_email_per_hour=100,
        auth_login_refresh_ip_limit_per_hour=100,
    )


def test_refresh_session_locks_current_refresh_authority_before_successor_issue() -> None:
    db = MagicMock(spec=Session)
    service = OidcLoginService(db, settings=_settings())
    member_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    record = SimpleNamespace(
        member_id=member_id,
        tenant_id=tenant_id,
        revoked_at=None,
        refresh_expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
    )
    member = SimpleNamespace(
        id=member_id,
        tenant_id=tenant_id,
        email_raw="owner@example.com",
        email_canonical="owner@example.com",
        is_active=lambda: True,
    )
    tenant = SimpleNamespace(
        name="Acme",
        slug="acme",
        plan="free",
        is_deleted=lambda: False,
        is_suspended=lambda: False,
    )
    successor = CustomerSessionResult(
        access_token="access",
        refresh_token="successor-refresh",
        expires_in=3600,
        refresh_expires_in=604800,
        tenant_id=str(tenant_id),
        email=member.email_raw,
        org_name="",
        slug="",
        plan="",
    )

    service._sessions.get_active_by_refresh_token_hash_for_update = MagicMock(return_value=record)  # type: ignore[method-assign]
    service._sessions.revoke = MagicMock(return_value=record)  # type: ignore[method-assign]
    service._members.get = MagicMock(return_value=member)  # type: ignore[method-assign]
    service._tenants.get = MagicMock(return_value=tenant)  # type: ignore[method-assign]

    with (
        patch.object(service, "_assert_session_enabled"),
        patch.object(service._abuse, "check_refresh_ip"),
        patch.object(service._abuse, "record"),
        patch.object(service, "_issue_session", return_value=successor) as issue_session,
    ):
        result = service.refresh_session(refresh_token="current-refresh-token", client_ip_hash="ip-hash")

    expected_hash = OidcLoginService._hash_refresh_token("current-refresh-token")
    call = service._sessions.get_active_by_refresh_token_hash_for_update.call_args  # type: ignore[attr-defined]
    assert call.args == (expected_hash,)
    assert isinstance(call.kwargs["now"], datetime)
    service._sessions.revoke.assert_called_once_with(record, revoked_at=call.kwargs["now"])  # type: ignore[attr-defined]
    issue_session.assert_called_once_with(member=member, email=member.email_raw, client_ip_hash="ip-hash")
    assert result.refresh_token == "successor-refresh"
