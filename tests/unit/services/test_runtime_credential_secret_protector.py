from __future__ import annotations

import pytest

from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector


def test_runtime_credential_secret_protector_encrypts_and_decrypts_without_plaintext_ciphertext() -> None:
    protector = RuntimeCredentialSecretProtector()

    ciphertext = protector.encrypt_secret("sk-provider-secret")

    assert ciphertext != "sk-provider-secret"
    assert "sk-provider-secret" not in ciphertext
    assert protector.decrypt_secret(ciphertext) == "sk-provider-secret"


def test_runtime_credential_secret_protector_rejects_empty_plaintext() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        RuntimeCredentialSecretProtector().encrypt_secret("")


def test_runtime_credential_secret_protector_fails_closed_for_invalid_ciphertext() -> None:
    with pytest.raises(ValueError, match="Failed to decrypt runtime credential ciphertext"):
        RuntimeCredentialSecretProtector().decrypt_secret("not-fernet-ciphertext")
