from __future__ import annotations

import base64

import pytest
from cryptography.fernet import Fernet

from backend.app.config import Settings
from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector


def test_runtime_credential_secret_protector_encrypts_and_decrypts_without_plaintext_ciphertext() -> None:
    protector = RuntimeCredentialSecretProtector(encryption_key=Fernet.generate_key())

    ciphertext = protector.encrypt_secret("sk-provider-secret")

    assert ciphertext != "sk-provider-secret"
    assert "sk-provider-secret" not in ciphertext
    assert protector.decrypt_secret(ciphertext) == "sk-provider-secret"


def test_runtime_credential_secret_protector_rejects_empty_plaintext() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        RuntimeCredentialSecretProtector(encryption_key=Fernet.generate_key()).encrypt_secret("")


def test_runtime_credential_secret_protector_fails_closed_for_invalid_ciphertext() -> None:
    with pytest.raises(ValueError, match="Failed to decrypt runtime credential ciphertext"):
        RuntimeCredentialSecretProtector(encryption_key=Fernet.generate_key()).decrypt_secret("not-fernet-ciphertext")


def test_runtime_credential_secret_protector_requires_a_current_key() -> None:
    settings = Settings.model_construct(runtime_secret_encryption_key=None, runtime_secret_encryption_key_prev=None)

    with pytest.raises(ValueError, match="AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY is required"):
        RuntimeCredentialSecretProtector(settings=settings)


@pytest.mark.parametrize("key", ["not-a-fernet-key", b"not-a-fernet-key"])
def test_runtime_credential_secret_protector_rejects_malformed_keys_without_echoing_them(key: str | bytes) -> None:
    with pytest.raises(ValueError, match="must be a valid Fernet key") as exc_info:
        RuntimeCredentialSecretProtector(encryption_key=key)

    assert str(key) not in str(exc_info.value)


@pytest.mark.parametrize("key_byte", [0x00, 0x01])
@pytest.mark.parametrize("previous", [False, True])
def test_runtime_credential_secret_protector_rejects_known_deterministic_keys_without_echoing_them(
    key_byte: int,
    previous: bool,
) -> None:
    rejected_key = base64.urlsafe_b64encode(bytes([key_byte]) * 32)
    kwargs: dict[str, bytes] = {"encryption_key": Fernet.generate_key()}
    if previous:
        kwargs["previous_encryption_key"] = rejected_key
    else:
        kwargs["encryption_key"] = rejected_key

    with pytest.raises(ValueError, match="must not use a known deterministic development key") as exc_info:
        RuntimeCredentialSecretProtector(**kwargs)

    assert rejected_key.decode() not in str(exc_info.value)


def test_runtime_credential_secret_protector_uses_previous_key_only_for_decryption() -> None:
    previous_key = Fernet.generate_key()
    current_key = Fernet.generate_key()
    previous = RuntimeCredentialSecretProtector(encryption_key=previous_key)
    rotated = RuntimeCredentialSecretProtector(
        encryption_key=current_key,
        previous_encryption_key=previous_key,
    )

    historical_ciphertext = previous.encrypt_secret("historic-secret")
    current_ciphertext = rotated.encrypt_secret("current-secret")

    assert rotated.decrypt_secret(historical_ciphertext) == "historic-secret"
    assert rotated.decrypt_secret(current_ciphertext) == "current-secret"
    with pytest.raises(ValueError, match="Failed to decrypt"):
        previous.decrypt_secret(current_ciphertext)


def test_runtime_credential_secret_protector_honors_supplied_settings_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_key = Fernet.generate_key().decode()
    monkeypatch.setenv("AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    settings = Settings.model_construct(
        runtime_secret_encryption_key=configured_key,
        runtime_secret_encryption_key_prev=None,
    )

    protector = RuntimeCredentialSecretProtector(settings=settings)
    ciphertext = protector.encrypt_secret("isolated-secret")

    assert (
        RuntimeCredentialSecretProtector(encryption_key=configured_key).decrypt_secret(ciphertext) == "isolated-secret"
    )


def test_runtime_credential_secret_protector_explicit_previous_key_overrides_settings_previous_key() -> None:
    current_key = Fernet.generate_key()
    settings_previous_key = Fernet.generate_key()
    explicit_previous_key = Fernet.generate_key()
    settings = Settings.model_construct(
        runtime_secret_encryption_key=current_key.decode(),
        runtime_secret_encryption_key_prev=settings_previous_key.decode(),
    )
    protector = RuntimeCredentialSecretProtector(settings=settings, previous_encryption_key=explicit_previous_key)

    assert (
        protector.decrypt_secret(
            RuntimeCredentialSecretProtector(encryption_key=explicit_previous_key).encrypt_secret("explicit-previous")
        )
        == "explicit-previous"
    )
    with pytest.raises(ValueError, match="Failed to decrypt"):
        protector.decrypt_secret(
            RuntimeCredentialSecretProtector(encryption_key=settings_previous_key).encrypt_secret("settings-previous")
        )


def test_runtime_credential_secret_protector_explicit_current_key_does_not_inherit_settings_previous_key() -> None:
    explicit_current_key = Fernet.generate_key()
    settings_previous_key = Fernet.generate_key()
    settings = Settings.model_construct(
        runtime_secret_encryption_key=Fernet.generate_key().decode(),
        runtime_secret_encryption_key_prev=settings_previous_key.decode(),
    )
    protector = RuntimeCredentialSecretProtector(settings=settings, encryption_key=explicit_current_key)

    with pytest.raises(ValueError, match="Failed to decrypt"):
        protector.decrypt_secret(
            RuntimeCredentialSecretProtector(encryption_key=settings_previous_key).encrypt_secret("settings-previous")
        )
