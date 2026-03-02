"""
Vault API — Omnipath v6.1 (The Scheduled Agent)

REST endpoints for managing encrypted external API credentials.

Endpoints:
    POST   /api/v1/vault/keys                          — Store/update a key
    GET    /api/v1/vault/keys                          — List all keys (metadata only)
    GET    /api/v1/vault/keys/{service}/{key_name}     — Get key metadata
    DELETE /api/v1/vault/keys/{service}/{key_name}     — Soft-delete a key

Note: GET endpoints return METADATA ONLY — plaintext credentials are never
      returned via the API.  Credentials are only decrypted internally by
      tools (e.g. RedditTool) that need them.

Built with Pride for Obex Blackvault
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from backend.api.routes.auth import get_current_user
from backend.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/vault", tags=["vault"])


# =============================================================================
# Request / Response Models
# =============================================================================


class StoreKeyRequest(BaseModel):
    """Request body for storing an external API key."""

    service: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Service identifier (e.g. 'reddit', 'twitter', 'linkedin')",
    )
    key_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Key name (e.g. 'production', 'staging')",
    )
    credentials: Dict[str, Any] = Field(
        ...,
        description="Plain-text credential dict — will be AES-256-GCM encrypted before storage",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional non-sensitive metadata (stored in plain text)",
    )


class KeyMetadataResponse(BaseModel):
    """API key metadata (no credentials)."""

    id: str
    tenant_id: str
    service: str
    key_name: str
    metadata: Dict[str, Any]
    is_active: bool
    created_at: Optional[str]
    updated_at: Optional[str]
    last_used_at: Optional[str]


class StoreKeyResponse(BaseModel):
    """Response after storing a key."""

    message: str
    key: KeyMetadataResponse


# =============================================================================
# Dependency
# =============================================================================


def _get_vault_service():
    """Retrieve the VaultService singleton from the main module."""
    try:
        from backend.main import get_vault_service
        return get_vault_service()
    except (ImportError, AttributeError):
        return None


# =============================================================================
# Endpoints
# =============================================================================


@router.post(
    "/keys",
    response_model=StoreKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Store or update an external API key",
)
async def store_key(
    request: StoreKeyRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Encrypt and store external API credentials.

    If a key with the same service + key_name already exists for this tenant,
    it is replaced (upsert semantics).

    The ``credentials`` dict is encrypted with AES-256-GCM before storage.
    Only the ciphertext, nonce, and GCM tag are persisted — plaintext is never
    written to the database.
    """
    vault = _get_vault_service()
    if vault is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vault service not available",
        )

    tenant_id = current_user["tenant_id"]
    user_id = current_user["user_id"]

    try:
        key = await vault.store_key(
            tenant_id=tenant_id,
            user_id=user_id,
            service=request.service,
            key_name=request.key_name,
            credentials=request.credentials,
            metadata=request.metadata,
        )
        return StoreKeyResponse(
            message=f"Key '{request.service}/{request.key_name}' stored successfully",
            key=key,
        )
    except Exception as exc:
        logger.error(f"Failed to store vault key: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store API key",
        )


@router.get(
    "/keys",
    response_model=List[KeyMetadataResponse],
    summary="List all stored API keys (metadata only)",
)
async def list_keys(
    service: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """
    List all stored API keys for the current tenant.

    Returns metadata only — plaintext credentials are never exposed via the API.
    Pass ``service=reddit`` to filter by service.
    """
    vault = _get_vault_service()
    if vault is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vault service not available",
        )

    tenant_id = current_user["tenant_id"]
    try:
        keys = await vault.list_keys(tenant_id=tenant_id, service=service)
        return keys
    except Exception as exc:
        logger.error(f"Failed to list vault keys: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list API keys",
        )


@router.get(
    "/keys/{service}/{key_name}",
    response_model=KeyMetadataResponse,
    summary="Get API key metadata by service and key name",
)
async def get_key_metadata(
    service: str,
    key_name: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Get metadata for a specific API key.

    Returns metadata only — plaintext credentials are never exposed via the API.
    """
    vault = _get_vault_service()
    if vault is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vault service not available",
        )

    tenant_id = current_user["tenant_id"]
    keys = await vault.list_keys(tenant_id=tenant_id, service=service)
    match = next((k for k in keys if k["key_name"] == key_name), None)

    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Key '{service}/{key_name}' not found",
        )
    return match


@router.delete(
    "/keys/{service}/{key_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an API key",
)
async def delete_key(
    service: str,
    key_name: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Soft-delete an API key (marks it inactive).

    The encrypted key material is retained in the database for audit purposes
    but will no longer be returned by any API or used by any tool.
    """
    vault = _get_vault_service()
    if vault is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vault service not available",
        )

    tenant_id = current_user["tenant_id"]
    deleted = await vault.delete_key(
        tenant_id=tenant_id,
        service=service,
        key_name=key_name,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Key '{service}/{key_name}' not found",
        )
