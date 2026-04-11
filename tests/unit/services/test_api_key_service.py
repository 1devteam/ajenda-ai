"""Unit tests for ApiKeyService."""

from __future__ import annotations

import pytest

from backend.services.api_key_service import ApiKeyService


def test_api_key_service_create_and_authenticate() -> None:
    """ApiKeyService creates a key and authenticates it correctly."""
    service = ApiKeyService()
    plaintext, record = service.create_key(tenant_id="tenant-a", scopes=("execution:queue",))
    principal = service.authenticate_machine(tenant_id="tenant-a", key_id=record.key_id, plaintext=plaintext)
    assert principal.tenant_id == "tenant-a"


def test_api_key_service_rejects_revoked_key() -> None:
    """ApiKeyService raises ValueError when authenticating a revoked key."""
    service = ApiKeyService()
    plaintext, record = service.create_key(tenant_id="tenant-a", scopes=())
    service.revoke_key(key_id=record.key_id)
    with pytest.raises(ValueError):
        service.authenticate_machine(tenant_id="tenant-a", key_id=record.key_id, plaintext=plaintext)


def test_api_key_service_count_active_keys() -> None:
    """count_active_keys returns the correct count for a tenant."""
    service = ApiKeyService()
    service.create_key(tenant_id="tenant-a", scopes=())
    service.create_key(tenant_id="tenant-a", scopes=())
    service.create_key(tenant_id="tenant-b", scopes=())
    assert service.count_active_keys(tenant_id="tenant-a") == 2
    assert service.count_active_keys(tenant_id="tenant-b") == 1
