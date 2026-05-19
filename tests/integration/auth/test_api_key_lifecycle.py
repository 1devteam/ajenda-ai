from backend.services.api_key_service import ApiKeyService


def test_api_key_lifecycle() -> None:
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

    assert principal.key_id == record.key_id

    service.revoke_key(key_id=record.key_id)
