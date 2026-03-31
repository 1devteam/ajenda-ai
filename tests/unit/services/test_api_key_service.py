import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.db.base import Base
from backend.services.api_key_service import ApiKeyService


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()


def test_api_key_service_create_and_authenticate() -> None:
    session = _session()
    service = ApiKeyService(session)
    plaintext, record = service.create_key(tenant_id="tenant-a", scopes=("execution:queue",))
    principal = service.authenticate_machine(tenant_id="tenant-a", key_id=record.key_id, plaintext=plaintext)
    assert principal.tenant_id == "tenant-a"


def test_api_key_service_rejects_revoked_key() -> None:
    session = _session()
    service = ApiKeyService(session)
    plaintext, record = service.create_key(tenant_id="tenant-a", scopes=())
    service.revoke_key(key_id=record.key_id)
    with pytest.raises(ValueError):
        service.authenticate_machine(tenant_id="tenant-a", key_id=record.key_id, plaintext=plaintext)
