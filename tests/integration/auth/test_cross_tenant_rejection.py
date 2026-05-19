import pytest

from backend.services.api_key_service import ApiKeyService


def test_cross_tenant_machine_access_rejected() -> None:
    service = ApiKeyService()

    plaintext, record = service.create_key(tenant_id="tenant-a", scopes=())

    with pytest.raises(ValueError):
        service.authenticate_machine(
            tenant_id="tenant-b",
            key_id=record.key_id,
            plaintext=plaintext,
        )
