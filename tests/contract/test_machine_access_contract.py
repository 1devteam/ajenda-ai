from backend.services.api_key_service import ApiKeyService


def test_machine_access_contract_returns_machine_executor_role() -> None:
    service = ApiKeyService()
    plaintext, record = service.create_key(tenant_id="tenant-a", scopes=())
    principal = service.authenticate_machine(tenant_id="tenant-a", key_id=record.key_id, plaintext=plaintext)
    assert principal.roles == ("machine_executor",)
