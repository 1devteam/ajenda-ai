"""WebhookSecretProtector — envelope encryption for webhook signing secrets.

Problem solved:
  The previous implementation stored webhook signing secrets as bcrypt hashes.
  This meant the HMAC-SHA256 signature on ``X-Ajenda-Signature-256`` was computed
  using the bcrypt hash as the key — a value the tenant never sees. Tenants could
  not verify the signature, making the header functionally useless.

Solution:
  Webhook secrets are now stored as Fernet-encrypted ciphertext in the
  ``secret_ciphertext`` column. At delivery time, the plaintext secret is
  decrypted and used as the HMAC key. Tenants receive the plaintext secret once
  at registration and can verify signatures using standard HMAC-SHA256.

Key management:
  The encryption key is a URL-safe base64-encoded 32-byte key loaded from the
  ``AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY`` environment variable. In production
  this must be set from a secrets manager (AWS Secrets Manager, Vault, etc.).
  In development/test, a deterministic test key is used if the env var is absent.

  Key rotation: to rotate the key, re-encrypt all existing ciphertexts using
  the new key (a background migration job). The old key can be kept in a
  ``AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY_PREV`` env var for a transition period.

Security properties:
  - Fernet uses AES-128-CBC with HMAC-SHA256 authentication (authenticated encryption).
  - Each encryption call produces a unique ciphertext (random IV per call).
  - Ciphertext is not reversible without the key.
  - The plaintext secret is never logged or stored unencrypted.
"""

from __future__ import annotations

import base64
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

# Environment variable name for the encryption key
_KEY_ENV_VAR = "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY"

# Deterministic test key — 32 zero bytes, base64-encoded.
# MUST NOT be used in production. The runtime contract validator enforces this.
_TEST_KEY = base64.urlsafe_b64encode(b"\x00" * 32)


class WebhookSecretProtector:
    """Encrypts and decrypts webhook signing secrets using Fernet symmetric encryption.

    Instantiate once per application lifetime (e.g. on app.state) and reuse.
    Thread-safe: Fernet is stateless after construction.
    """

    def __init__(self, *, encryption_key: bytes | None = None) -> None:
        """Initialise the protector with a Fernet key.

        Args:
            encryption_key: URL-safe base64-encoded 32-byte key. If None, the
                            key is read from the ``AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY``
                            environment variable. Falls back to the test key if
                            neither is provided (development/test only).
        """
        if encryption_key is not None:
            key = encryption_key
        else:
            env_key = os.environ.get(_KEY_ENV_VAR)
            key = env_key.encode() if env_key else _TEST_KEY
        self._fernet = Fernet(key)

    @classmethod
    def generate_key(cls) -> str:
        """Generate a new random Fernet key suitable for use as the encryption key.

        Returns the key as a URL-safe base64-encoded string. Store this in your
        secrets manager and set it as ``AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY``.
        """
        return Fernet.generate_key().decode()

    def generate_secret(self) -> tuple[str, str]:
        """Generate a new webhook signing secret and return (plaintext, ciphertext).

        The plaintext is a 32-byte (256-bit) cryptographically random hex string.
        The ciphertext is the Fernet-encrypted plaintext, safe to store in the DB.

        Returns:
            (plaintext_secret, ciphertext): plaintext is shown once to the tenant;
            ciphertext is stored in ``webhook_endpoints.secret_ciphertext``.
        """
        plaintext = secrets.token_hex(32)  # 64 hex chars = 256 bits of entropy
        ciphertext = self._fernet.encrypt(plaintext.encode()).decode()
        return plaintext, ciphertext

    def decrypt_secret(self, ciphertext: str) -> str:
        """Decrypt a stored ciphertext back to the plaintext signing secret.

        Args:
            ciphertext: The Fernet ciphertext stored in ``secret_ciphertext``.

        Returns:
            The plaintext signing secret for use as the HMAC key.

        Raises:
            ValueError: If the ciphertext is invalid or was encrypted with a
                        different key (e.g. after key rotation without migration).
        """
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise ValueError(
                "Failed to decrypt webhook secret ciphertext. "
                "The ciphertext may be corrupt or was encrypted with a different key. "
                "Check AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY and run a key rotation "
                "migration if the key was recently changed."
            ) from exc
