from __future__ import annotations

import pytest

from backend.domain.api_key_record import ApiKeyRecordModel
from backend.services.api_key_service import ApiKeyService


def test_api_key_service_create_and_authenticate() -> None:
    service = ApiKeyService()

    plaintext, record = service.create_key(
        tenant_id="tenant-a",
        scopes=("execution:queue",),
    )

    principal = service.authenticate_machine(
        tenant_id="tenant-a",
        key_id=record.key_id,
        plaintext=plaintext,
    )

    assert isinstance(record, ApiKeyRecordModel)
    assert principal.tenant_id == "tenant-a"


def test_api_key_service_rejects_revoked_key() -> None:
    service = ApiKeyService()

    plaintext, record = service.create_key(tenant_id="tenant-a", scopes=())
    service.revoke_key(key_id=record.key_id)

    with pytest.raises(ValueError):
        service.authenticate_machine(
            tenant_id="tenant-a",
            key_id=record.key_id,
            plaintext=plaintext,
        )


def test_api_key_service_memory_mode_returns_record_not_wrapper() -> None:
    service = ApiKeyService()

    plaintext, record = service.create_key(
        tenant_id="tenant-a",
        scopes=("execution:queue",),
    )

    principal = service.authenticate_machine(
        tenant_id="tenant-a",
        key_id=record.key_id,
        plaintext=plaintext,
    )

    assert isinstance(record, ApiKeyRecordModel)
    assert record.tenant_id == "tenant-a"
    assert principal.tenant_id == "tenant-a"
