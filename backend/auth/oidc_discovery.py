"""OIDC provider discovery helpers."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DISCOVERY_CACHE_TTL_SECONDS = 600


@dataclass(frozen=True, slots=True)
class OidcProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


class OidcDiscoveryClient:
    """Fetch and cache OIDC provider metadata from the issuer well-known URL."""

    def __init__(self, *, issuer: str) -> None:
        self._issuer = issuer.rstrip("/")
        self._metadata: OidcProviderMetadata | None = None
        self._fetched_at: float = 0.0

    def get_metadata(self) -> OidcProviderMetadata:
        now = time.monotonic()
        if self._metadata is None or now - self._fetched_at > _DISCOVERY_CACHE_TTL_SECONDS:
            self._refresh()
        assert self._metadata is not None
        return self._metadata

    def _refresh(self) -> None:
        url = f"{self._issuer}/.well-known/openid-configuration"
        try:
            response = httpx.get(url, timeout=5.0)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        except Exception as exc:
            logger.error("oidc_discovery_failed", extra={"issuer": self._issuer, "error": str(exc)})
            if self._metadata is not None:
                return
            raise RuntimeError("OIDC discovery failed") from exc

        authorization_endpoint = payload.get("authorization_endpoint")
        token_endpoint = payload.get("token_endpoint")
        jwks_uri = payload.get("jwks_uri")
        issuer = payload.get("issuer") or self._issuer
        if not all(
            isinstance(value, str) and value.strip() for value in (authorization_endpoint, token_endpoint, jwks_uri)
        ):
            raise RuntimeError("OIDC discovery document missing required endpoints")

        self._metadata = OidcProviderMetadata(
            issuer=str(issuer).rstrip("/"),
            authorization_endpoint=str(authorization_endpoint),
            token_endpoint=str(token_endpoint),
            jwks_uri=str(jwks_uri),
        )
        self._fetched_at = time.monotonic()
