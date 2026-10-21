"""Runtime credential encryption with explicit previous-key read support.

New ciphertext always uses the current key. A configured previous key may
decrypt existing ciphertext during a controlled rotation window.

Provider secrets must only be decrypted at authorized runtime boundaries.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken

from backend.app.config import Settings, get_settings

_REJECTED_RUNTIME_FERNET_KEYS = frozenset(base64.urlsafe_b64encode(bytes([value]) * 32) for value in (0x00, 0x01))


class RuntimeCredentialSecretProtector:
    """Encrypt with the current Fernet key; decrypt with current or previous."""

    def __init__(
        self,
        *,
        encryption_key: str | bytes | None = None,
        previous_encryption_key: str | bytes | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Build the protector from explicit keys or one validated Settings instance.

        An explicit current key wins over ``settings``. An explicit previous key
        wins over ``settings`` when a current key is sourced from ``settings``.
        When an explicit current key is supplied without an explicit previous
        key, no previous key is inherited from ``settings``. There is no
        development fallback: credential encryption must never silently use a
        deterministic key.
        """

        if encryption_key is None:
            runtime_settings = settings or get_settings()
            encryption_key = runtime_settings.runtime_secret_encryption_key
            if previous_encryption_key is None:
                previous_encryption_key = runtime_settings.runtime_secret_encryption_key_prev

        current_key = self._validated_key(encryption_key, current=True)
        previous_key = self._validated_key(previous_encryption_key, current=False)
        assert current_key is not None

        self._fernet = Fernet(current_key)
        self._decryptors = [self._fernet]

        if previous_key is not None and previous_key != current_key:
            self._decryptors.append(Fernet(previous_key))

    @staticmethod
    def _validated_key(value: str | bytes | None, *, current: bool) -> bytes | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            if current:
                raise ValueError("AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY is required for runtime credential encryption")
            return None
        key = value.encode("utf-8") if isinstance(value, str) else value
        name = "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY" if current else "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY_PREV"
        if key in _REJECTED_RUNTIME_FERNET_KEYS:
            raise ValueError(f"{name} must not use a known deterministic development key")
        try:
            Fernet(key)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a valid Fernet key") from exc
        return key

    @classmethod
    def generate_key(cls) -> str:
        return Fernet.generate_key().decode()

    def encrypt_secret(self, plaintext: str) -> str:
        if not plaintext:
            raise ValueError("runtime credential secret must be non-empty")
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt_secret(self, ciphertext: str) -> str:
        for decryptor in self._decryptors:
            try:
                return decryptor.decrypt(ciphertext.encode()).decode()
            except InvalidToken:
                continue

        raise ValueError(
            "Failed to decrypt runtime credential ciphertext. "
            "Check AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY and "
            "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY_PREV."
        )
