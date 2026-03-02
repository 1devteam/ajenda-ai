"""
API Key Vault Service — Omnipath v6.1 (The Scheduled Agent)

Secure storage and retrieval of external API credentials.

Security Design:
  - AES-256-GCM authenticated encryption (via Python ``cryptography`` library).
  - Encryption key derived from the application SECRET_KEY using HKDF-SHA256.
  - Only ciphertext, nonce, and GCM tag are stored in the database.
  - The plaintext key material NEVER touches the database.
  - Per-record 12-byte random nonces prevent ciphertext reuse.
  - Tenant isolation enforced at every read/write operation.

Usage:
    vault = VaultService(session_factory, settings)
    await vault.store_key(tenant_id, user_id, "reddit", "production", {...})
    creds = await vault.get_key(tenant_id, "reddit", "production")

Built with Pride for Obex Blackvault
"""

import base64
import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.core.logging_config import get_logger, LoggerMixin
from backend.database.models import ExternalAPIKey

logger = get_logger(__name__)


class VaultService(LoggerMixin):
    """
    Manages encrypted external API key storage.

    All keys are encrypted with AES-256-GCM before being written to the
    ``external_api_keys`` table.  The encryption key is derived from the
    application SECRET_KEY and is never stored anywhere.

    Supported services (extensible):
        - ``reddit``    — PRAW credentials (client_id, client_secret, username, password)
        - ``twitter``   — Twitter/X API v2 credentials
        - ``linkedin``  — LinkedIn API credentials
        - ``openai``    — OpenAI API key (for per-tenant overrides)
        - ``anthropic`` — Anthropic API key (for per-tenant overrides)
        - ``custom``    — Any other service
    """

    # HKDF info string — changing this invalidates all existing keys
    _HKDF_INFO = b"omnipath-vault-v1"

    def __init__(
        self,
        session_factory: async_sessionmaker,
        secret_key: str,
    ) -> None:
        """
        Args:
            session_factory: AsyncSessionLocal — opens per-operation sessions.
            secret_key:      Application SECRET_KEY (from settings).
        """
        self._session_factory = session_factory
        self._aes_key = self._derive_key(secret_key)

    # =========================================================================
    # Public API
    # =========================================================================

    async def store_key(
        self,
        tenant_id: str,
        user_id: str,
        service: str,
        key_name: str,
        credentials: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Encrypt and store external API credentials.

        If a key with the same (tenant_id, service, key_name) already exists,
        it is replaced (upsert semantics).

        Args:
            tenant_id:   Owning tenant.
            user_id:     User performing the operation.
            service:     Service identifier (e.g. ``"reddit"``).
            key_name:    Human-readable key name (e.g. ``"production"``).
            credentials: Plain-text credential dict (will be encrypted).
            metadata:    Optional non-sensitive metadata dict.

        Returns:
            Serialised ExternalAPIKey dict (no plaintext credentials).
        """
        # Encrypt the credentials
        plaintext = json.dumps(credentials).encode("utf-8")
        nonce = os.urandom(12)  # 96-bit nonce for AES-GCM
        aesgcm = AESGCM(self._aes_key)
        ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext, None)

        encrypted_value = base64.b64encode(ciphertext_with_tag).decode("ascii")
        nonce_b64 = base64.b64encode(nonce).decode("ascii")

        # Check for existing key (upsert)
        existing = await self._find_key(tenant_id, service, key_name)

        async with self._session_factory() as session:
            if existing:
                await session.execute(
                    update(ExternalAPIKey)
                    .where(ExternalAPIKey.id == existing["id"])
                    .values(
                        encrypted_value=encrypted_value,
                        nonce=nonce_b64,
                        key_metadata=metadata or {},
                        is_active=True,
                        updated_at=datetime.utcnow(),
                    )
                )
                await session.commit()
                result = await self._find_key(tenant_id, service, key_name)
                self.log_info(
                    f"Vault key updated: {service}/{key_name}",
                    tenant_id=tenant_id,
                )
                return result
            else:
                key_id = f"key_{uuid.uuid4().hex[:16]}"
                key = ExternalAPIKey(
                    id=key_id,
                    tenant_id=tenant_id,
                    created_by=user_id,
                    service=service,
                    key_name=key_name,
                    encrypted_value=encrypted_value,
                    nonce=nonce_b64,
                    key_metadata=metadata or {},
                    is_active=True,
                )
                session.add(key)
                await session.commit()
                await session.refresh(key)
                result = self._key_to_dict(key)
                self.log_info(
                    f"Vault key stored: {service}/{key_name}",
                    tenant_id=tenant_id,
                    key_id=key_id,
                )
                return result

    async def get_key(
        self,
        tenant_id: str,
        service: str,
        key_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Decrypt and return credentials for a given service/key_name.

        Args:
            tenant_id: Owning tenant (enforces isolation).
            service:   Service identifier.
            key_name:  Key name.

        Returns:
            Plain-text credential dict, or None if not found.
        """
        async with self._session_factory() as session:
            query = (
                select(ExternalAPIKey)
                .where(ExternalAPIKey.tenant_id == tenant_id)
                .where(ExternalAPIKey.service == service)
                .where(ExternalAPIKey.key_name == key_name)
                .where(ExternalAPIKey.is_active.is_(True))
            )
            result = await session.execute(query)
            key = result.scalar_one_or_none()

            if key is None:
                return None

            # Decrypt
            credentials = self._decrypt(key.encrypted_value, key.nonce)

            # Update last_used_at
            await session.execute(
                update(ExternalAPIKey)
                .where(ExternalAPIKey.id == key.id)
                .values(last_used_at=datetime.utcnow())
            )
            await session.commit()

            return credentials

    async def list_keys(
        self,
        tenant_id: str,
        service: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List all stored keys for a tenant (metadata only, no credentials).

        Args:
            tenant_id: Owning tenant.
            service:   Optional filter by service.

        Returns:
            List of key metadata dicts (no plaintext credentials).
        """
        async with self._session_factory() as session:
            query = (
                select(ExternalAPIKey)
                .where(ExternalAPIKey.tenant_id == tenant_id)
                .where(ExternalAPIKey.is_active.is_(True))
            )
            if service:
                query = query.where(ExternalAPIKey.service == service)
            query = query.order_by(ExternalAPIKey.created_at.desc())
            result = await session.execute(query)
            keys = result.scalars().all()
            return [self._key_to_dict(k) for k in keys]

    async def delete_key(
        self,
        tenant_id: str,
        service: str,
        key_name: str,
    ) -> bool:
        """
        Soft-delete a key (marks is_active=False).

        Args:
            tenant_id: Owning tenant.
            service:   Service identifier.
            key_name:  Key name.

        Returns:
            True if deleted, False if not found.
        """
        async with self._session_factory() as session:
            query = (
                select(ExternalAPIKey)
                .where(ExternalAPIKey.tenant_id == tenant_id)
                .where(ExternalAPIKey.service == service)
                .where(ExternalAPIKey.key_name == key_name)
                .where(ExternalAPIKey.is_active.is_(True))
            )
            result = await session.execute(query)
            key = result.scalar_one_or_none()

            if key is None:
                return False

            await session.execute(
                update(ExternalAPIKey)
                .where(ExternalAPIKey.id == key.id)
                .values(is_active=False, updated_at=datetime.utcnow())
            )
            await session.commit()
            self.log_info(
                f"Vault key deleted: {service}/{key_name}",
                tenant_id=tenant_id,
            )
            return True

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _derive_key(self, secret_key: str) -> bytes:
        """
        Derive a 32-byte AES-256 key from the application SECRET_KEY using HKDF-SHA256.

        HKDF provides domain separation via the info string, ensuring the vault
        key is cryptographically independent from the JWT signing key even if
        they share the same source material.
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=self._HKDF_INFO,
        )
        return hkdf.derive(secret_key.encode("utf-8"))

    def _decrypt(self, encrypted_value: str, nonce_b64: str) -> Dict[str, Any]:
        """
        Decrypt a stored credential blob.

        Args:
            encrypted_value: Base64-encoded ciphertext+GCM tag.
            nonce_b64:       Base64-encoded 12-byte nonce.

        Returns:
            Decrypted credential dict.

        Raises:
            ValueError: If decryption fails (wrong key or tampered data).
        """
        try:
            ciphertext_with_tag = base64.b64decode(encrypted_value)
            nonce = base64.b64decode(nonce_b64)
            aesgcm = AESGCM(self._aes_key)
            plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
            return json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            self.log_error(f"Vault decryption failed: {exc}", exc_info=True)
            raise ValueError("Failed to decrypt vault key — possible key rotation or tampering")

    async def _find_key(
        self, tenant_id: str, service: str, key_name: str
    ) -> Optional[Dict[str, Any]]:
        """Find a key by (tenant_id, service, key_name) and return its metadata dict."""
        async with self._session_factory() as session:
            query = (
                select(ExternalAPIKey)
                .where(ExternalAPIKey.tenant_id == tenant_id)
                .where(ExternalAPIKey.service == service)
                .where(ExternalAPIKey.key_name == key_name)
            )
            result = await session.execute(query)
            key = result.scalar_one_or_none()
            return self._key_to_dict(key) if key else None

    @staticmethod
    def _key_to_dict(key: ExternalAPIKey) -> Dict[str, Any]:
        """Serialise an ExternalAPIKey to a plain dict (no credentials)."""
        return {
            "id": key.id,
            "tenant_id": key.tenant_id,
            "service": key.service,
            "key_name": key.key_name,
            "metadata": key.key_metadata,
            "is_active": key.is_active,
            "created_at": key.created_at.isoformat() if key.created_at else None,
            "updated_at": key.updated_at.isoformat() if key.updated_at else None,
            "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        }
