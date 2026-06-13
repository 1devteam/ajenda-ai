"""Runtime credential secret encryption for provider credentials.

Provider runtime credentials are encrypted at rest and decrypted only inside the
live credential runtime repository immediately before `CredentialRuntimeAuthority`
validates and returns runtime-only material.
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken

_KEY_ENV_VAR = "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY"
_TEST_KEY = base64.urlsafe_b64encode(b"\x00" * 32)


class RuntimeCredentialSecretProtector:
    """Encrypt and decrypt provider runtime credential secrets using Fernet."""

    def __init__(self, *, encryption_key: bytes | None = None) -> None:
        if encryption_key is not None:
            key = encryption_key
        else:
            env_key = os.environ.get(_KEY_ENV_VAR)
            key = env_key.encode() if env_key else _TEST_KEY
        self._fernet = Fernet(key)

    @classmethod
    def generate_key(cls) -> str:
        return Fernet.generate_key().decode()

    def encrypt_secret(self, plaintext: str) -> str:
        if not plaintext:
            raise ValueError("runtime credential secret must be non-empty")
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt_secret(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise ValueError(
                "Failed to decrypt runtime credential ciphertext. "
                "Check AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY and run key rotation if the key changed."
            ) from exc
