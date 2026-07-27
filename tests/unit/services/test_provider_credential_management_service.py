from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.config import Settings
from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.services.credentials.management_service import (
    PLATFORM_MASTER_CREDENTIAL_TYPE,
    ProviderCredentialManagementError,
    ProviderCredentialManagementService,
)
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    ProviderRuntimeCredential.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    yield factory
    engine.dispose()


def _settings(*, platform_master: bool = False, **overrides: object) -> Settings:
    return Settings.model_construct(
        env="test",
        hubspot_crm_adapter_public_host="hubspot-crm-ingress",
        hubspot_platform_master_key_enabled=platform_master,
        hubspot_platform_master_key="platform-test-key" if platform_master else None,
        runtime_secret_encryption_key=RuntimeCredentialSecretProtector().generate_key(),
        **overrides,
    )


def _service(session, **settings_kwargs: object) -> ProviderCredentialManagementService:
    service = ProviderCredentialManagementService(session, settings=_settings(**settings_kwargs))
    service._audit = MagicMock()
    return service


def test_register_hubspot_external_crm_credential(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    with session_factory() as session:
        service = _service(session)
        result = service.register(
            tenant_id=tenant_id,
            credential_id="hubspot-crm",
            provider="external_crm",
            integration="hubspot",
            secret_value="tenant-hubspot-pak",
            actor_id="user-1",
        )
        session.commit()

    assert result.summary.provider == "external_crm"
    assert result.summary.credential_type == "api_key"
    assert "hubspot-crm-ingress" in result.summary.trusted_destination_hosts
    assert "crm.research" in result.summary.allowed_actions
    assert result.warning is None


def test_register_platform_master_requires_operator_key(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    with session_factory() as session:
        service = _service(session, platform_master=False)
        with pytest.raises(ProviderCredentialManagementError, match="platform master"):
            service.register(
                tenant_id=tenant_id,
                credential_id="hubspot-shared",
                provider="external_crm",
                use_platform_master_key=True,
                actor_id="user-1",
            )


def test_register_platform_master_emits_warning(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    with session_factory() as session:
        service = _service(session, platform_master=True)
        result = service.register(
            tenant_id=tenant_id,
            credential_id="hubspot-shared",
            provider="external_crm",
            use_platform_master_key=True,
            actor_id="user-1",
        )
        session.commit()

    assert result.summary.credential_type == PLATFORM_MASTER_CREDENTIAL_TYPE
    assert result.summary.uses_platform_master_key is True
    assert result.warning is not None
    assert "WARNING" in result.warning


def test_register_smtp_email_credential(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    smtp_secret = '{"host":"smtp.example.com","port":587,"user":"sender@example.com","password":"secret"}'
    with session_factory() as session:
        service = _service(session)
        result = service.register(
            tenant_id=tenant_id,
            credential_id="smtp-outbound",
            provider="external_email",
            integration="smtp",
            secret_value=smtp_secret,
            actor_id="user-1",
        )
        session.commit()

    assert result.summary.provider == "external_email"
    assert result.summary.credential_type == "smtp"
    assert "gtm.email_send" in result.summary.allowed_actions


def test_register_linkedin_read_credential(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    with session_factory() as session:
        service = _service(session)
        result = service.register(
            tenant_id=tenant_id,
            credential_id="linkedin-read",
            provider="external_read_provider",
            integration="linkedin",
            secret_value="linkedin-oauth-token",
            actor_id="user-1",
        )
        session.commit()

    assert "linkedin.profile_read" in result.summary.allowed_actions
    assert "api.linkedin.com" in result.summary.trusted_destination_hosts


def test_register_salesforce_read_requires_instance_host(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    with session_factory() as session:
        service = _service(session)
        with pytest.raises(ProviderCredentialManagementError, match="trusted_destination_hosts"):
            service.register(
                tenant_id=tenant_id,
                credential_id="salesforce-read",
                provider="external_read_provider",
                integration="salesforce",
                secret_value="sf-oauth-token",
                actor_id="user-1",
            )


def test_register_salesforce_read_derives_instance_host_from_json_secret(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    secret = '{"provider_kind":"salesforce","access_token":"sf-access","instance_url":"https://acme.my.salesforce.com"}'
    with session_factory() as session:
        service = _service(session)
        result = service.register(
            tenant_id=tenant_id,
            credential_id="salesforce-read",
            provider="external_read_provider",
            integration="salesforce",
            secret_value=secret,
            actor_id="user-1",
        )
        session.commit()

    assert result.summary.trusted_destination_hosts == ["acme.my.salesforce.com"]


def test_register_google_calendar_read_credential(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    with session_factory() as session:
        service = _service(session)
        result = service.register(
            tenant_id=tenant_id,
            credential_id="google-calendar-read",
            provider="external_read_provider",
            integration="google_calendar",
            secret_value="calendar-oauth-token",
            actor_id="user-1",
        )
        session.commit()

    assert "google_calendar.events_read" in result.summary.allowed_actions
    assert result.summary.trusted_destination_hosts == ["www.googleapis.com"]


def test_register_google_contacts_read_credential(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    with session_factory() as session:
        service = _service(session)
        result = service.register(
            tenant_id=tenant_id,
            credential_id="google-contacts-read",
            provider="external_read_provider",
            integration="google_contacts",
            secret_value="contacts-oauth-token",
            actor_id="user-1",
        )
        session.commit()

    assert "provider.external_read" in result.summary.allowed_actions
    assert result.summary.trusted_destination_hosts == ["people.googleapis.com"]


def test_register_github_read_credential(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    with session_factory() as session:
        service = _service(session)
        result = service.register(
            tenant_id=tenant_id,
            credential_id="github-read",
            provider="external_read_provider",
            integration="github",
            secret_value="github-oauth-token",
            actor_id="user-1",
        )
        session.commit()

    assert "github.repo_read" in result.summary.allowed_actions
    assert result.summary.trusted_destination_hosts == ["api.github.com"]


def test_register_salesforce_read_credential(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    with session_factory() as session:
        service = _service(session)
        result = service.register(
            tenant_id=tenant_id,
            credential_id="salesforce-read",
            provider="external_read_provider",
            integration="salesforce",
            secret_value="sf-oauth-token",
            trusted_destination_hosts=["acme.my.salesforce.com"],
            actor_id="user-1",
        )
        session.commit()

    assert "salesforce.soql_read" in result.summary.allowed_actions
    assert result.summary.trusted_destination_hosts == ["acme.my.salesforce.com"]


def test_register_same_credential_id_updates_existing_secret(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    with session_factory() as session:
        service = _service(session)
        first = service.register(
            tenant_id=tenant_id,
            credential_id="gmail-email",
            provider="external_email",
            integration="gmail",
            secret_value='{"access_token":"token-a"}',
            actor_id="user-1",
        )
        second = service.register(
            tenant_id=tenant_id,
            credential_id="gmail-email",
            provider="external_email",
            integration="gmail",
            secret_value='{"access_token":"token-b"}',
            actor_id="user-1",
        )
        session.commit()

    assert first.summary.credential_id == second.summary.credential_id
    with session_factory() as session:
        listed = _service(session).list_credentials(tenant_id=tenant_id)
    assert len(listed) == 1
    assert listed[0].enabled is True
    assert listed[0].revoked is False


def test_revoke_and_list_credentials(session_factory) -> None:
    tenant_id = str(uuid.uuid4())
    with session_factory() as session:
        service = _service(session)
        service.register(
            tenant_id=tenant_id,
            credential_id="hubspot-crm",
            provider="external_crm",
            secret_value="pak",
            actor_id="user-1",
        )
        session.commit()

    with session_factory() as session:
        service = _service(session)
        listed = service.list_credentials(tenant_id=tenant_id)
        assert len(listed) == 1
        revoked = service.revoke(tenant_id=tenant_id, credential_id="hubspot-crm", actor_id="user-1")
        session.commit()
        assert revoked.revoked is True
