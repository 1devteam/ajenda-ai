"""Resolve Salesforce bearer tokens from stored credential secrets with optional OAuth refresh."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.services.credentials.salesforce_oauth_client import (
    SalesforceOAuthError,
    SalesforceOAuthTokenBundle,
    refresh_salesforce_access_token,
    resolve_salesforce_oauth_client_config,
)

TOKEN_REFRESH_SKEW_SECONDS = 60
PROVIDER_KIND = "salesforce"


class SalesforceRuntimeTokenError(ValueError):
    """Deterministic Salesforce runtime token resolution failure."""


@dataclass(slots=True)
class SalesforceRuntimeTokenResolution:
    access_token: str
    updated_secret: str | None = None


def is_salesforce_oauth_secret(secret_value: str) -> bool:
    stripped = secret_value.strip()
    if not stripped.startswith("{"):
        return False
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("provider_kind") == PROVIDER_KIND:
        return True
    return isinstance(payload.get("access_token"), str) and isinstance(payload.get("instance_url"), str)


def serialize_salesforce_oauth_secret(*, bundle: SalesforceOAuthTokenBundle) -> str:
    document = {
        "provider_kind": PROVIDER_KIND,
        "access_token": bundle.access_token,
        "refresh_token": bundle.refresh_token,
        "expires_at": bundle.expires_at,
        "instance_url": bundle.instance_url,
        "scopes": list(bundle.scopes),
        "token_type": bundle.token_type,
    }
    return json.dumps(document, sort_keys=True)


def resolve_salesforce_credential_secret(
    secret_value: str,
    *,
    auto_refresh: bool = True,
    redirect_uri: str = "http://localhost:5173/credentials/salesforce/callback",
) -> SalesforceRuntimeTokenResolution:
    stripped = secret_value.strip()
    if not stripped:
        raise SalesforceRuntimeTokenError("salesforce credential secret is empty")

    if not is_salesforce_oauth_secret(stripped):
        return SalesforceRuntimeTokenResolution(access_token=stripped)

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise SalesforceRuntimeTokenError("salesforce oauth secret must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise SalesforceRuntimeTokenError("salesforce oauth secret must be a JSON object")

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise SalesforceRuntimeTokenError("salesforce oauth secret missing access_token")

    refresh_token = payload.get("refresh_token")
    expires_at = payload.get("expires_at")
    if not auto_refresh or not isinstance(refresh_token, str) or not refresh_token.strip():
        return SalesforceRuntimeTokenResolution(access_token=access_token.strip())

    if not _token_expired(expires_at):
        return SalesforceRuntimeTokenResolution(access_token=access_token.strip())

    try:
        client = resolve_salesforce_oauth_client_config(redirect_uri=redirect_uri)
    except SalesforceOAuthError as exc:
        raise SalesforceRuntimeTokenError(
            "salesforce access token expired and Salesforce OAuth client is not configured for refresh"
        ) from exc

    try:
        refreshed = refresh_salesforce_access_token(client=client, refresh_token=refresh_token)
    except SalesforceOAuthError as exc:
        raise SalesforceRuntimeTokenError(f"salesforce token refresh failed: {exc}") from exc

    instance_url = payload.get("instance_url")
    if not isinstance(instance_url, str) or not instance_url.strip():
        instance_url = refreshed.instance_url

    merged = SalesforceOAuthTokenBundle(
        access_token=refreshed.access_token,
        refresh_token=refreshed.refresh_token or refresh_token.strip(),
        expires_at=refreshed.expires_at,
        instance_url=instance_url if isinstance(instance_url, str) else refreshed.instance_url,
        scopes=refreshed.scopes,
        token_type=refreshed.token_type,
    )
    return SalesforceRuntimeTokenResolution(
        access_token=merged.access_token,
        updated_secret=serialize_salesforce_oauth_secret(bundle=merged),
    )


def _token_expired(expires_at: Any) -> bool:
    if not isinstance(expires_at, str) or not expires_at.strip():
        return True
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= datetime.now(tz=UTC) + timedelta(seconds=TOKEN_REFRESH_SKEW_SECONDS)
