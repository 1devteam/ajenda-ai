from backend.services.api_key_service import ApiKeyService


def test_cross_tenant_machine_access_rejected(pg_session) -> None:
    service = ApiKeyService(pg_session)
    plaintext, record = service.create_key(tenant_id="tenant-a", scopes=())
    pg_session.flush()

    result = service.authenticate_machine(
        tenant_id="tenant-b",
        key_id=record.key_id,
        plaintext=plaintext,
    )
    assert result is None
