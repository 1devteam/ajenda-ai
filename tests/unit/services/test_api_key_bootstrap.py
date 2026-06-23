"""Unit tests for bootstrap API key behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.auth.permissions import Permission
from backend.services.api_key_service import ApiKeyService


def test_bootstrap_key_uses_signup_bootstrap_permissions() -> None:
    service = ApiKeyService()
    expires_at = datetime.now(UTC) + timedelta(hours=72)
    plaintext, record = service.create_key(
        tenant_id="tenant-a",
        roles=("signup_bootstrap",),
        purpose="bootstrap",
        expires_at=expires_at,
    )
    principal = service.authenticate_machine(
        tenant_id="tenant-a",
        key_id=record.key_id,
        plaintext=plaintext,
    )
    assert principal is not None
    assert Permission.MISSION_CREATE in principal.permissions
    assert Permission.ACCOUNT_READ in principal.permissions
    assert Permission.BILLING_READ not in principal.permissions
    assert Permission.BILLING_MANAGE not in principal.permissions
    assert Permission.API_KEYS_CREATE not in principal.permissions
    assert principal.roles == ("signup_bootstrap",)


def test_bootstrap_key_rejects_expired_key() -> None:
    service = ApiKeyService()
    expires_at = datetime.now(UTC) - timedelta(minutes=1)
    plaintext, record = service.create_key(
        tenant_id="tenant-a",
        roles=("signup_bootstrap",),
        purpose="bootstrap",
        expires_at=expires_at,
    )
    principal = service.authenticate_machine(
        tenant_id="tenant-a",
        key_id=record.key_id,
        plaintext=plaintext,
        now=datetime.now(UTC),
    )
    assert principal is None


def test_tenant_operator_key_has_api_key_permissions() -> None:
    service = ApiKeyService()
    plaintext, record = service.create_key(
        tenant_id="tenant-a",
        roles=("tenant_operator",),
        purpose="operational",
    )
    principal = service.authenticate_machine(
        tenant_id="tenant-a",
        key_id=record.key_id,
        plaintext=plaintext,
    )
    assert principal is not None
    assert Permission.API_KEYS_CREATE in principal.permissions
    assert Permission.MISSION_MANAGE in principal.permissions
    assert Permission.ACCOUNT_READ in principal.permissions
    assert Permission.BILLING_READ in principal.permissions
    assert Permission.BILLING_MANAGE in principal.permissions


def test_create_bootstrap_key_requires_expiry() -> None:
    service = ApiKeyService()
    with pytest.raises(ValueError, match="bootstrap API keys require expires_at"):
        service.create_key(
            tenant_id="tenant-a",
            roles=("signup_bootstrap",),
            purpose="bootstrap",
        )
