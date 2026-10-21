from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.config import Settings, get_settings
from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector
from backend.services.credentials.sqlalchemy_repository import SQLAlchemyCredentialRuntimeRepository


def test_oauth_refresh_reencrypts_with_current_key_after_previous_key_decryption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_key = Fernet.generate_key()
    current_key = Fernet.generate_key()
    old_protector = RuntimeCredentialSecretProtector(encryption_key=previous_key)
    configured_redirect_uri = "http://test.invalid/credentials/gmail/callback"
    monkeypatch.setenv("AJENDA_GMAIL_OAUTH_REDIRECT_URI", "http://ambient.invalid/credentials/gmail/callback")
    get_settings.cache_clear()
    settings = Settings.model_construct(
        env="test",
        runtime_secret_encryption_key=current_key.decode(),
        runtime_secret_encryption_key_prev=previous_key.decode(),
        gmail_oauth_redirect_uri=configured_redirect_uri,
    )
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    ProviderRuntimeCredential.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
    try:
        with factory() as session:
            session.add(
                ProviderRuntimeCredential(
                    id="credential-1",
                    tenant_id="tenant-a",
                    credential_id="gmail-read",
                    provider="external_email",
                    integration="gmail",
                    credential_type="api_key",
                    enabled=True,
                    revoked=False,
                    deleted=False,
                    allowed_actions=["gtm.email_check"],
                    allowed_side_effect_classes=["external_read"],
                    trusted_destination_hosts=["gmail.googleapis.com"],
                    secret_ciphertext=old_protector.encrypt_secret("old-oauth-bundle"),
                )
            )
            session.commit()

        resolver_calls: list[dict[str, object]] = []

        def resolve_gmail(*_args: object, **kwargs: object) -> SimpleNamespace:
            resolver_calls.append(kwargs)
            return SimpleNamespace(
                access_token="fresh-access-token",
                updated_secret="refreshed-oauth-bundle",
            )

        monkeypatch.setattr(
            "backend.services.credentials.sqlalchemy_repository.resolve_gmail_credential_secret", resolve_gmail
        )
        repository = SQLAlchemyCredentialRuntimeRepository(session_factory=factory, settings=settings)
        record = repository.get_visible_for_tenant(tenant_id="tenant-a", credential_id="gmail-read")

        assert record is not None
        assert record.secret_value == "fresh-access-token"
        assert resolver_calls == [{"auto_refresh": True, "redirect_uri": configured_redirect_uri}]
        with factory() as session:
            row = session.execute(select(ProviderRuntimeCredential)).scalar_one()
            refreshed_ciphertext = row.secret_ciphertext

        assert RuntimeCredentialSecretProtector(encryption_key=current_key).decrypt_secret(refreshed_ciphertext) == (
            "refreshed-oauth-bundle"
        )
        with pytest.raises(ValueError, match="Failed to decrypt"):
            old_protector.decrypt_secret(refreshed_ciphertext)
    finally:
        engine.dispose()
        get_settings.cache_clear()
